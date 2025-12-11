#ifdef TIMING_SIMULATION
#ifndef TLB_H
#define TLB_H

#include <set>
#include <cstdint>
#include "cache.h"
#include "common.h"
#include "delay_queue.h"
#include "m2ndp_config.h"

namespace NDPSim {

// -----------------------------
// Latency parameters (cycles)
// -----------------------------
#ifndef PROBE_CYCLES
#define PROBE_CYCLES 560
#endif
#ifndef ATS_CYCLES
#define ATS_CYCLES 4000
#endif
#ifndef PRI_CYCLES
#define PRI_CYCLES 32000
#endif

// -----------------------------
// Page-table change injection
// -----------------------------
// 변화 확률 (ppm 단위). 예: 20000 → 2%
#ifndef CHANGE_PPM
#define CHANGE_PPM 50000
#endif
// 변화 시드 갱신 주기
#ifndef CHANGE_PERIOD_CYCLES
#define CHANGE_PERIOD_CYCLES 1107
#endif

// 지연큐 한 사이클 처리량
#ifndef DRAM_TLB_DEQUEUE_PER_CYCLE
#define DRAM_TLB_DEQUEUE_PER_CYCLE 8
#endif

class Tlb {
 public:
  Tlb(int id, M2NDPConfig *config, std::string tlb_config,
      fifo_pipeline<mem_fetch> *to_mem_queue);

  void set_ideal_tlb();
  bool fill_port_free();
  bool data_port_free();

  bool full();
  bool full(uint64_t mf_size);

  // 메모리에서 TLB 라인 응답 도착 → 지연을 부과하고 만료 시 on-chip TLB fill
  void fill(mem_fetch *mf);
  bool waiting_for_fill(mem_fetch *mf);

  // on-chip TLB lookup 발행 (miss면 tlb_mf 생성)
  void access(mem_fetch* mf);

  bool data_ready();
  mem_fetch* get_data();
  void pop_data();

  void cycle();
  void bank_access_cycle();

  CacheStats get_stats();

  // 상위에서 activity 판단용
  bool active() const;

 private:
  // DRAM-TLB 라인 주소(rolling 없음, 단일 실험)
  uint64_t get_tlb_addr(uint64_t addr);
  // write 여부
  bool is_write_req(mem_fetch* tlb_fill_mf) const;

  // page-table 변화 스케줄링
  void maybe_advance_change(uint64_t now_cycle);
  inline bool change_pick(uint64_t vpn) const;

 private:
  int m_id;
  int m_page_size;
  int m_tlb_entry_size;
  int m_tlb_hit_latency;
  bool m_ideal_tlb = false;

  M2NDPConfig *m_config;
  fifo_pipeline<mem_fetch> *m_to_mem_queue;

  fifo_pipeline<mem_fetch> m_finished_mf;

  // on-chip lookup latency
  DelayQueue<mem_fetch*> m_tlb_request_queue;

  // Probe/ATS/PRI 지연 (min-heap, 완료시각 순)
  DelayQueue<mem_fetch*> m_dram_tlb_latency_queue;

  // DRAM-TLB 존재 집합(워밍업 가정이지만 nullptr 방지 및 관리용)
  std::set<uint64_t> *m_accessed_tlb_addr;
  std::set<uint64_t>  m_local_dramtlb_fallback;

  CacheConfig m_tlb_config;
  Cache *m_tlb;

  // 변화 주입 상태
  static uint64_t s_change_salt;
  static uint64_t s_last_change_cycle;
};

}  // namespace NDPSim
#endif
#endif
