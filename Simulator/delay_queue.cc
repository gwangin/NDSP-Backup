#ifdef TIMING_SIMULATION
#include "delay_queue.h"
#include "common.h"
#include "mem_fetch.h"

namespace NDPSim {

template <typename T>
void DelayQueue<T>::push(T data, int delay) {
  assert(m_only_latency);
  m_size++;
  m_heap.push(typename DelayQueue<T>::QueueEntry{data, m_cycle + (uint64_t)delay, m_seq++});
}

template <typename T>
void DelayQueue<T>::push(T data, int delay, int interval) {
  assert(m_issued == false);
  m_size++;
  m_heap.push(typename DelayQueue<T>::QueueEntry{data, m_cycle + (uint64_t)delay, m_seq++});
  if (!m_only_latency) m_issued = true;
  m_interval = interval;
}

template <typename T>
void DelayQueue<T>::pop() {
  assert(!empty());
  m_heap.pop();
  m_size--;
}

template <typename T>
T DelayQueue<T>::top() {
  assert(!empty());
  return m_heap.top().data;
}

template <typename T>
bool DelayQueue<T>::empty() const {
  if (m_heap.empty()) return true;
  return m_heap.top().ready_cycle > m_cycle;
}

template <typename T>
bool DelayQueue<T>::queue_empty() const {
  return m_heap.empty();
}

template <typename T>
bool DelayQueue<T>::full() {
  return m_issued || (m_max_size > 0 && m_size >= m_max_size);
}

template <typename T>
void DelayQueue<T>::cycle() {
  if (m_interval > 0) m_interval--;
  if (m_interval <= 0) m_issued = false;
  m_cycle++;
}

// 명시적 인스턴스
template class DelayQueue<std::pair<NdpInstruction, Context>>;
template class DelayQueue<RequestInfo*>;
template class DelayQueue<NDPSim::mem_fetch*>;

}  // namespace NDPSim
#endif
