#ifdef TIMING_SIMULATION
#include "tlb.h"
#include "mem_fetch.h"

namespace NDPSim {

static inline uint64_t vpn_of(uint64_t addr, uint64_t page_sz) {
  return addr / page_sz;
}

// 변화 주입 초기값
uint64_t Tlb::s_change_salt = 0;
uint64_t Tlb::s_last_change_cycle = 0;

Tlb::Tlb(int id, M2NDPConfig* config, std::string tlb_config,
         fifo_pipeline<mem_fetch>* to_mem_queue)
    : m_id(id), m_config(config), m_to_mem_queue(to_mem_queue) {
  m_page_size = config->get_tlb_page_size();

  // on-chip TLB 구성
  m_tlb_config.init(tlb_config, config);
  m_tlb = new ReadOnlyCache("tlb", m_tlb_config, id, 0, m_to_mem_queue);
  m_tlb_entry_size = m_config->get_tlb_entry_size();

  m_finished_mf = fifo_pipeline<mem_fetch>(
      "tlb_finished_mf", 0, m_config->get_request_queue_size());

  // 온칩 lookup 지연
  m_tlb_request_queue = DelayQueue<mem_fetch*>(
      "tlb_req_queue", /*only_latency=*/true, m_config->get_request_queue_size());

  // Probe/ATS/PRI 지연 (min-heap)
  m_dram_tlb_latency_queue = DelayQueue<mem_fetch*>(
      "dram_tlb_latency_queue", /*only_latency=*/true, m_config->get_request_queue_size());

  m_tlb_hit_latency = m_config->get_tlb_hit_latency();

  // DRAM-TLB 존재 집합: nullptr 방지
  m_accessed_tlb_addr = m_config->get_accessed_tlb_addr();
  if (!m_accessed_tlb_addr) {
    m_accessed_tlb_addr = &m_local_dramtlb_fallback;
  }
}

void Tlb::set_ideal_tlb() {
  m_ideal_tlb = true;
  m_tlb_hit_latency = 0;
}
bool Tlb::fill_port_free() { return m_tlb->fill_port_free(); }
bool Tlb::data_port_free() { return m_tlb->data_port_free(); }

bool Tlb::full() { return full(0); }

// 대기큐(lookup) + 지연큐(Probe/ATS/PRI) 합산으로 과적 방지
bool Tlb::full(uint64_t mf_size) {
  return m_tlb_request_queue.size()
       + m_dram_tlb_latency_queue.size()
       + (int)mf_size >= m_config->get_request_queue_size();
}

bool Tlb::waiting_for_fill(mem_fetch* mf) {
  return m_tlb->waiting_for_fill(mf);
}

bool Tlb::is_write_req(mem_fetch* tlb_fill_mf) const {
  mem_fetch* orig = tlb_fill_mf ? tlb_fill_mf->get_tlb_original_mf() : nullptr;
  if (!orig) return false;
  return orig->is_write() || (orig->get_access_type() == GLOBAL_ACC_W);
}

// 메모리 응답 → DRAM-TLB probe 560c + (변화 걸리면) ATS/PRI 추가
// 지연 만료 시 bank_access_cycle()에서 on-chip TLB fill
void Tlb::fill(mem_fetch* mf) {
  mf->current_state = "TLB Fill";

  // 원 요청 주소의 VPN 기준으로 변화 여부 판단
  mem_fetch* orig = mf->get_tlb_original_mf();
  const uint64_t orig_addr = orig ? orig->get_addr() : 0;
  const uint64_t vpn = vpn_of(orig_addr, (uint64_t)m_page_size);

  // DRAM-TLB은 warm 가정이므로 먼저 probe 비용
  int delay = PROBE_CYCLES;

  // 변화가 걸린 VPN이면 추가 ATS/PRI 부과
  if (change_pick(vpn)) {
    const bool is_wr = is_write_req(mf);
    delay += is_wr ? PRI_CYCLES : ATS_CYCLES;
  }

  // 참고: 존재 집합은 warm이라 가정하지만, 누락 방지를 위해 관찰된 tlb_addr를 등록
  const uint64_t tlb_addr = mf->get_addr();
  m_accessed_tlb_addr->insert(tlb_addr);

  // 지연큐로 보냄 (만료 후 on-chip TLB fill)
  m_dram_tlb_latency_queue.push(mf, delay);
}

void Tlb::access(mem_fetch* mf) {
  assert(!full());
  m_tlb_request_queue.push(mf, m_tlb_hit_latency);
}

bool Tlb::data_ready() { return !m_finished_mf.empty(); }
mem_fetch* Tlb::get_data() { return m_finished_mf.top(); }
void Tlb::pop_data() { m_finished_mf.pop(); }

void Tlb::cycle() {
  m_tlb->cycle();
  m_tlb_request_queue.cycle();
  m_dram_tlb_latency_queue.cycle();

  maybe_advance_change(m_config->get_ndp_cycle());
}

void Tlb::bank_access_cycle() {
  // (1) 지연 만료 → on-chip TLB fill
  for (int i = 0; i < DRAM_TLB_DEQUEUE_PER_CYCLE; ++i) {
    if (m_dram_tlb_latency_queue.empty()) break;
    mem_fetch* mf = m_dram_tlb_latency_queue.top();
    m_tlb->fill(mf, m_config->get_ndp_cycle());
    m_dram_tlb_latency_queue.pop();
  }

  // (2) on-chip TLB access 완료 → 원요청 완료
  if (m_tlb->access_ready() && !m_finished_mf.full()) {
    mem_fetch* mf = m_tlb->pop_next_access();
    if (mf->is_request()) mf->set_reply();
    m_finished_mf.push(mf->get_tlb_original_mf());
    delete mf;
  }

  // (3) on-chip TLB lookup 발행
  if (!m_tlb_request_queue.empty() && data_port_free()) {
    mem_fetch* mf = m_tlb_request_queue.top();
    uint64_t addr = mf->get_addr();
    uint64_t tlb_addr = get_tlb_addr(addr);

    mem_fetch* tlb_mf =
        new mem_fetch(tlb_addr, TLB_ACC_R, READ_REQUEST, m_tlb_entry_size,
                      CXL_OVERHEAD, m_config->get_ndp_cycle());
    tlb_mf->set_from_ndp(true);
    tlb_mf->set_ndp_id(m_id);
    tlb_mf->set_tlb_original_mf(mf);
    tlb_mf->set_channel(m_config->get_channel_index(tlb_addr));

    std::deque<CacheEvent> events;
    CacheRequestStatus stat = MISS;
    if (!m_ideal_tlb)
      stat = m_tlb->access(tlb_addr, m_config->get_ndp_cycle(), tlb_mf, events);

    if ((stat == HIT || m_ideal_tlb) && !m_finished_mf.full()) {
      m_finished_mf.push(mf);
      delete tlb_mf;
      m_tlb_request_queue.pop();
    } else if (stat == HIT && m_finished_mf.full()) {
      delete tlb_mf;
    } else if (stat != RESERVATION_FAIL) {
      m_tlb_request_queue.pop();
    } else if (stat == RESERVATION_FAIL) {
      delete tlb_mf;
    }
  }
}

CacheStats Tlb::get_stats() { return m_tlb->get_stats(); }

// DRAM-TLB 라인 주소(단일 실험: epoch 오프셋 없음)
uint64_t Tlb::get_tlb_addr(uint64_t addr) {
  return addr / m_page_size * m_tlb_entry_size + DRAM_TLB_BASE;
}

// 변화 시드 주기 갱신
void Tlb::maybe_advance_change(uint64_t now_cycle) {
  if (CHANGE_PERIOD_CYCLES <= 0) return;
  if (now_cycle >= s_last_change_cycle + (uint64_t)CHANGE_PERIOD_CYCLES) {
    s_change_salt++;
    s_last_change_cycle = now_cycle;
  }
}

// 균등 서브셋 선택: hash(vpn ^ salt) % 1e6 < CHANGE_PPM
bool Tlb::change_pick(uint64_t vpn) const {
  uint64_t x = vpn ^ s_change_salt;
  // SplitMix64
  x += 0x9e3779b97f4a7c15ULL;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
  x = x ^ (x >> 31);
  return (x % 1000000ULL) < (uint64_t)CHANGE_PPM;
}

bool Tlb::active() const {
  return !m_tlb_request_queue.queue_empty()
      || !m_dram_tlb_latency_queue.queue_empty()
      || !m_finished_mf.empty();
}

}  // namespace NDPSim
#endif
