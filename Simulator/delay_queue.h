#ifdef TIMING_SIMULATION
#ifndef PairDelayQueue_H
#define PairDelayQueue_H

#include <cassert>
#include <cstdint>
#include <queue>
#include <string>
#include <vector>

namespace NDPSim {

// Min-heap 기반 지연큐: 가장 이른 완료시각 항목이 먼저 준비됨
template <typename T>
class DelayQueue {
 public:
  DelayQueue() {}
  DelayQueue(std::string name, bool only_latency, int max_size)
      : m_only_latency(only_latency),
        m_name(name),
        m_interval(0),
        m_cycle(0),
        m_max_size(max_size),
        m_issued(false),
        m_size(0),
        m_seq(0) {}
  DelayQueue(std::string name) : DelayQueue(name, false, -1) {}

  void push(T data, int delay);
  void push(T data, int delay, int interval);
  void pop();
  T top();

  // 조회자 (const-qualified)
  int  size()  const { return m_size; }
  bool empty() const;        // 준비(ready) 여부 기준
  bool queue_empty() const;  // 물리적으로 큐 비었는지
  bool full();

  void cycle();

 private:
  struct QueueEntry {
    T        data;
    uint64_t ready_cycle;
    uint64_t seq;           // 동일 ready 시 입력 순 유지
  };
  struct Cmp {
    bool operator()(const QueueEntry& a, const QueueEntry& b) const {
      if (a.ready_cycle != b.ready_cycle) return a.ready_cycle > b.ready_cycle; // min-heap
      return a.seq > b.seq;
    }
  };

  std::string m_name;
  int m_interval;
  uint64_t m_cycle;
  int m_size;
  int m_max_size;
  bool m_issued;
  bool m_only_latency;
  uint64_t m_seq;

  std::priority_queue<QueueEntry, std::vector<QueueEntry>, Cmp> m_heap;
};

}  // namespace NDPSim
#endif
#endif
