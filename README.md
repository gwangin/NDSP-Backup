README는 크게 3가지 설명을 담고 있다.
1. 사전 공부 목록
2. Motivation: redis, Spark에서 page table 변화 관측
3. Simulator 동작과 NDSP 구현

# 사전 공부 목록

**아래 목록은 이 연구를 이해하기 위해 반드시 한 번씩은 짚고 넘어가야 하는 개념들이다.
논문·자료는 핵심일 뿐이니, 필요하면 추가로 찾아서 보아야 한다.**

---

## 1. CXL (Compute Express Link)

1. **CXL Spec 읽기**

   * 최신 버전 spec 을 다운로드해서 최소 다음 챕터는 정독한다.

     1. Chapter 2
     2. Chapter 3
     3. Chapter 7
     4. Appendix

2. **DAX(Direct Access) 이해**

   * 문서: [https://docs.kernel.org/filesystems/dax.html](https://docs.kernel.org/filesystems/dax.html)
   * DAX 가 **page cache 를 건너뛰고 직접 persistent memory에 접근하는 메커니즘**이라는 점,
   * 파일 시스템과 VA–PA 매핑이 어떻게 연결되는지까지 정리해두면 좋다.
   * CXL memory가 OS에 인식되는 방식 중 하나이므로 잘 이해해두기.

---

## 2. GPU 계열 SVM/UVM vs CXL NDP 메모리

***핵심 질문:***
“기존 GPU/가속기의 SVM/UVM 환경과, CXL memory 위에 있는 NDP core의 주소 공간·page table 관계가 무엇이 다른가?”

1. **SVA/SVM (Shared Virtual Address / Shared Virtual Memory)**

   * 참고 논문:

     * *Shared Virtual Memory: Its Design and Performance Implications for Diverse Applications*
       [https://arxiv.org/pdf/2405.06811](https://arxiv.org/pdf/2405.06811)
     * *In-Depth Analyses of Unified Virtual Memory System for GPU Accelerated Computing*
   * 정리할 것:

     1. CPU와 GPU가 **어떤 수준까지 VA를 공유**하는지
     2. page fault 경로에 **어떤 하드웨어/소프트웨어가 개입**하는지
     3. migration / coherence 정책이 NDP 와 어떤 점에서 다른지

2. **UVM (Unified Virtual Memory, NVIDIA 계열)**

   * NVIDIA 공식 문서들 + 다음 논문:

     * *GPUVM: GPU-driven Unified Virtual Memory*
       [https://arxiv.org/pdf/2411.05309](https://arxiv.org/pdf/2411.05309)
   * 정리할 것:

     1. CPU page table vs GPU page table 의 **동기화 구조**
     2. UVM fault handling 이 host 중심인지, device 중심인지
     3. 이 구조가 CXL NDP 메모리에서의 page table 상태와 **어디가 같고 어디가 다른지**

---

## 3. ATS / PRI / IOMMU

1. **IOMMU 기본**

   * 슬라이드:
     [https://pages.cs.wisc.edu/~basu/isca_iommu_tutorial/IOMMU_TUTORIAL_ASPLOS_2016.pdf](https://pages.cs.wisc.edu/~basu/isca_iommu_tutorial/IOMMU_TUTORIAL_ASPLOS_2016.pdf)
   * 논문 예시:

     * *rIOMMU: Efficient IOMMU for I/O Devices that Employ Ring Buffers*
   * 정리할 것:

     1. IOMMU 가 **device 입장에서의 MMU**라는 점
     2. DMA 요청이 IOMMU를 어떻게 거쳐서 PA로 변환되는지
     3. page fault 시 어떤 경로로 **host OS가介入**하는지

2. **ATS (Address Translation Service) / PRI (Page Request Interface)**

   * 논문:

     * *VPRI: Efficient I/O page fault handling via software-hardware Co-design for IaaS clouds*
       [https://dl.acm.org/doi/10.1145/3694715.3695957](https://dl.acm.org/doi/10.1145/3694715.3695957)
     * *To PRI or Not PRI, That's the question* (OSDI’25)
       [https://www.usenix.org/conference/osdi25/presentation/wang-yun](https://www.usenix.org/conference/osdi25/presentation/wang-yun)
   * 정리할 것:

     1. ATS 가 어떤 형식으로 **translation cache**를 제공하는지
     2. PRI가 page fault 를 어떤 포맷으로 host 에 보고하는지
     3. CXL 장치(NDP)가 이 프로토콜을 쓸 때, **latency·bandwidth·병목**이 어디서 생기는지

---

## 4. Linux HMM 및 mmu_notifier

1. **HMM(Heterogeneous Memory Management)**

   * 문서:

     * [https://www.kernel.org/doc/html/v5.0/vm/hmm.html](https://www.kernel.org/doc/html/v5.0/vm/hmm.html)
   * GPU 등 device 가 **CPU page table 을 공유하거나 따라 다니는 구조**를 어떻게 구현하는지 확인.

2. **mmu_notifier**

   * 문서:

     * [https://docs.kernel.org/mm/mmu_notifier.html](https://docs.kernel.org/mm/mmu_notifier.html)
   * VA → PA 매핑이 바뀔 때,
     커널이 device driver 쪽으로 **invalidate / update 콜백을 보내는 메커니즘** 이해하기.

---

# Page Table 변화 측정 – 실험 코드 정리

## 1. 기본 아이디어

### 1.1 `/proc/<pid>/pagemap` snapshot 방식

* Linux는 `/proc/<pid>/pagemap` 을 통해
  “**프로세스의 VA가 어느 PFN에 매핑돼 있는지**”를 사용자 공간에서 읽을 수 있게 해준다.
* 목표는 특정 application의 동작 중에 **page table(PTE) 가 얼마나 자주, 어떻게 변하는지**를 측정하는 것.

### 1.2 snapshot 비교에서 보고 싶은 것

일정 주기(예: 5초)마다 pagemap snapshot을 찍고,
연속된 두 snapshot 을 비교해서 아래 세 가지를 기록한다.

1. **Added PTE**

   * 이전 snapshot 에는 없었는데, 현재 snapshot 에 새로 등장한 `(VPN → PFN)` 매핑
2. **Changed PTE**

   * VPN 은 그대로인데 **PFN 이 바뀐 경우**
   * 예: migration, compaction, NUMA rebalancing 등
3. **Removed PTE**

   * 이전 snapshot 에 있었는데, 현재 snapshot 에서는 사라진 매핑

***만약 백업되어 있는 스크립트/코드가 직관적으로 보이지 않으면,
위 개념만 이해한 뒤 새로 짜는 게 오히려 빠를 수도 있다.***

---

## 2. 공통 실험 조건

***중요: 모든 실험에서 application 자체와 무관하게 page table 을 바꿔버리는 OS 기능들은 꺼둬야 한다.***

* 반드시 비활성화해야 하는 옵션 예:

  1. **AutoNUMA**
  2. **Transparent Huge Pages (THP)**

이 두 가지가 켜져 있으면, application 동작과 상관없이
커널이 알아서 페이지를 옮기거나 hugepage로 바꾸면서 PTE 가 변해 버리므로 OFF한 후 실험해야한다.

---

## 3. Redis 기반 실험

### 3.1 파일/스크립트 역할

작업 디렉터리 예시: `~/KVStore/pt_capture`

1. `snap_pagetable.py`

   * `/proc/<pid>/pagemap` 을 읽어서
     각 페이지에 대해 `VPN, status, PFN` 등의 정보를 추출한다.
   * 결과를 **압축된 CSV (`pt_<epoch>.csv.gz`)** 로 저장 → 하나가 한 snapshot.

2. `capture_loop.sh`

   * 주기적으로 `snap_pagetable.py` 를 호출해 snapshot 을 쌓는다.
   * 각 스냅샷 직후 `append_last_diff.py` (또는 유사 스크립트)를 호출해서
     바로 직전 snapshot 과의 차이를 계산해 로그에 추가.

3. `start_capture.sh`

   * `capture_loop.sh` 를 **백그라운드**에서 실행하는 wrapper.
   * 실험 시작 시 한 번 실행해 두고, application 이 종료될 때까지 계속 돌도록 한다.

4. `diff_pagetable.py`

   * 두 snapshot 파일을 입력으로 받아,

     1. added PTE
     2. changed PTE
     3. removed PTE
        개수를 계산한다.
   * CSV 기준으로 line-by-line 비교 + `(VPN → PFN)` 매핑 차이를 분석하는 구조.

5. `analyze_diff.py`

   * 모든 snapshot pair 에 대해 `diff_pagetable.py` 를 호출하여
     **전체 time series diff** 를 만드는 스크립트.
   * 실험이 끝난 뒤 한 번 돌려서,

     * “시간에 따라 PTE 변화량이 어떻게 변하는지”
     * “어떤 구간에서 activity 가 집중되는지”
       를 볼 수 있는 summary를 만든다.

---

### 3.2 실험 방법

***AutoNUMA / THP 가 꺼져 있는지 먼저 확인하고 진행할 것.***

실행 예시:

```bash
cd ~/KVStore/pt_capture
PORT=6380 ENABLE_COW=0 RUN_FOR_SECS=600 THREADS=32 CAP_INTERVAL=5 ./run_two_phase.sh
````

* `PORT=6380`

  * Redis instance 가 사용할 포트.
* `ENABLE_COW=0`

  * Copy-on-write 빈도를 제어(실험 환경에 맞게).
* `RUN_FOR_SECS=600`

  * 전체 workload 실행 시간 (초 단위).
* `THREADS=32`

  * 클라이언트 쓰레드 수.
* `CAP_INTERVAL=5`

  * **5초마다** pagetable snapshot 을 찍는 설정.

`run_two_phase.sh` 는 보통:

1. Redis 서버/클라이언트를 올리고,
2. `start_capture.sh` 로 snapshot capture 를 시작한 뒤,
3. 특정 workload 를 두 phase 로 나눠서 실행하게 되어 있다.

---

### 3.3 실험 결과물

실험이 끝나면 대략 아래와 같은 파일들이 생성된다.

1. `snapshots/pt_*.csv.gz`

   * pagemap snapshot 들.
   * 파일 이름에 epoch 번호 혹은 timestamp 가 들어간다.

2. `diffs/stream_summary.csv`

   * 각 snapshot interval (예: 5초) 마다

     * added / changed / removed / RSS
       를 정리한 summary CSV.

3. `diffs/stream_totals.txt`

   * 전체 실험 기간 동안 누적된 page table 변화량 요약.

4. `logs/capture.log`

   * snapshot 캡처 루프의 로그 (오류, 경고 등 확인용).

---

## 4. Spark 기반 OLAP 실험

### 4.1 파일/스크립트 역할

작업 디렉터리 예시: `~/spark/olap_snapshot_pt`

1. `env.sh`

   * Spark 실행 환경 설정.

     * `SPARK_HOME` 위치 설정
     * 필요하면 `JAVA_HOME` / PATH 조정
   * Spark 관련 바이너리(`spark-submit`) 를 제대로 찾기 위한 초기화 스크립트.

2. `olap_app.py`

   * Spark 기반 OLAP workload 를 실행한다.
   * 동시에 **JVM PID 를 기록**해서 pagemap 캡처 대상 프로세스를 명시한다.
   * 예: 특정 `spark-submit` job 의 driver / executor PID 통합 관리.

3. `start_olap_with_capture.sh`

   * 전체 워크플로우:

     1. `env.sh` 로 환경 세팅
     2. `spark-submit` 를 통해 `olap_app.py` 실행
     3. JVM PID 확인
     4. 해당 PID 를 대상으로 `capture_loop.sh` 시작

4. `snap_pagetable.py`

   * Redis 실험과 동일하게, `/proc/<pid>/pagemap` 을 읽어서 snapshot 생성.
   * 결과는 `pt_<timestamp>.csv.gz` 와 같은 형식.

5. `diff_pagetable.py`

   * 두 snapshot 간 added / changed / removed PTE 개수 계산.

6. `append_change_log.py`

   * 각 interval 에 대해:

     * added/changed/removed 갯수
     * 현재 RSS (resident set size) 등
       을 한 줄 log 로 append.
   * Spark workload 종료 후에는 이 로그 한 파일만 보면 된다.

7. `capture_loop.sh`

   * PID 가 살아있는 동안:

     1. `snap_pagetable.py` 호출 → snapshot
     2. `diff_pagetable.py` + `append_change_log.py` 호출 → 변화량 계산 및 로그 기록
   * interval 은 인자로 전달 (예: 5초).

---

### 4.2 실험 방법

***이 실험 역시 AutoNUMA / THP 를 반드시 끄고 진행한다.***

실행 예시:

```bash
cd ~/spark/olap_snapshot_pt
source env.sh
echo "$SPARK_HOME"
which spark-submit

./start_olap_with_capture.sh 8g 50 5
```

* `8g`

  * Spark executor/driver 메모리 설정 예시.
* `50`

  * OLAP workload 내 반복 횟수 혹은 데이터 규모(스크립트에 따라 의미 달라질 수 있음).
* `5`

  * pagemap snapshot 캡처 interval (초).

실행이 끝난 다음에는:

* `log/pt_changes.log`

  * 각 interval 의 added/changed/removed/RSS 가 한 줄씩 기록된 로그 파일만 보면 전체 경향을 파악할 수 있다.

---

## 5. 정리

1. **연구 배경 이해에 필요한 개념**은

   * CXL / DAX
   * SVM/UVM, GPUVM
   * ATS/PRI/IOMMU
   * Linux HMM + mmu_notifier
     쪽을 우선순위로 두고 공부한다.

2. **Page table 변화 측정**은

   * `/proc/<pid>/pagemap` snapshot 을 주기적으로 찍고,
   * snapshot 간 diff 를 통해 **added / changed / removed PTE** 를 세는 구조다.

3. Redis, Spark 실험 코드들은 이 공통 아이디어를
   각각의 workload 에 맞춰 스크립트 체인으로 묶어 놓은 것이다.

필요하면 여기 적힌 개념과 흐름을 기준으로 스크립트를 새로 만들어도 된다.
핵심은 *“어떤 application 이 어떤 패턴으로 page table 을 바꾸는지 관찰하는 것 그리고 가장 확실한 방법은 proc/pagemap을 확인하는 것”* 이다.
현재 motivation에서 관측된 page table이 변경되는 workload가 두개 뿐이어서 application이 동작중에 page table이 변경되는 일반적이라고 하는 주장은 무리가 있을 수 있다. 그래서 page table이 변경되는 것을 추가로 찾아야할 수 있다.
그리고 redis의 경우 AOF, RDB snapshot 등에 의한 fork후 COW에 의해 page table이 변경되는 것으로 예측하고 있다. 이 경우 우리의 NDSP 디자인을 그대로 사용할 수 없으므로 디자인을 변경, 추가하여야 한다.








# M2NDP Timing Simulator & TLB 확장 구현 설명

이 문서는 M2NDP-public 시뮬레이터의 **동작 방식(특히 timing 모드)** 과
그 위에 추가한 **TLB + DRAM-TLB + ATS/PRI 부하 모델링 구현**을 정리한 것이다.

> 시뮬레이터에는 Functional / Timing 두 모드가 있지만,
> **여기서는 Timing 모드만을 대상으로 설명**한다.
> 실제 실험 및 결과도 Timing 모드 기준이다.

---

## 목차

1. [전체 구조 개요](#0-전체-구조-개요)
2. [Trace 생성 흐름](#1-trace-생성-흐름-make_tracesh--runnerpy--kernel-class)
3. [예시: `LtINT64Kernel`](#2-예시-ltint64kernel--input-scaling과-isa)
4. [Trace 파일 포맷](#3-trace-파일-포맷-traceg_inputdata_outputdata-launchtxt)
5. [Timing Simulator 주요 컴포넌트](#4-timing-simulator-주요-컴포넌트)
6. [TLB 확장 구현(추가 코드)](#5-tlb-확장-구현-이-연구에서-추가한-부분)
7. [요약 및 실험 시 유용한 포인트](#6-요약-및-실험-시-유용한-포인트)

---

## 0. 전체 구조 개요

Timing 모드에서의 흐름은 다음과 같다.

1. Python 스크립트가 workload별로
   **커널 코드(`*.traceg`), 메모리 이미지(`*_input.data`, `*_output.data`), launch 정보(`launch.txt`)** 를 생성한다.
2. C++ 시뮬레이터는 이 파일들을 읽어서

   * 입력 데이터를 `HashMemoryMap` 에 적재하고,
   * `NdpUnit` / `SubCore` 가 μthread를 생성해 커널을 실행하며,
   * load/store를 `mem_fetch` 로 발행해서 TLB, cache, DRAM, CXL link 등을 **cycle 기반으로** 모사한다.
3. TLB 코드(추가 구현)가

   * DRAM-TLB(또는 shadow page table) probe,
   * ATS(Address Translation Service),
   * PRI(Page Request Interface),
   * page-table 변경 확률
     을 반영하여 NDP memory access latency를 변경한다.

아래부터

* 1–4장은 **원래 시뮬레이터 동작 설명**
* 5장은 **추가로 구현한 TLB/DelayQueue 관련 내용**

으로 나눠서 정리한다. 이때 원래 시뮬레이터 동작 설명에서 scaling은 추가 구현된 내용이다.

---

## 1. Trace 생성 흐름 (`make_trace.sh` → `runner.py` → Kernel class)

### 1.1 `make_trace.sh` – 페이지 크기 & 워킹셋 크기 설정

```bash
#!/bin/bash

echo "Generating traces for 4KB pages"
export PAGE_SHIFT=12   # 4KB

# ==== OLAP (워킹셋 ~32~48 MiB 타깃) ====
python3 examples/runner.py --kernel LtINT64Kernel     --output_dir ./traces/imdb_lt_int64       --skip_functional_sim --arg 1
echo "lt_int64 done"
python3 examples/runner.py --kernel GtEqLtINT64Kernel --output_dir ./traces/imdb_gteq_lt_int64   --skip_functional_sim --arg 1
echo "gteq_lt_int64 done"
python3 examples/runner.py --kernel GtLtFP32Kernel    --output_dir ./traces/imdb_gt_lt_fp32      --skip_functional_sim --arg 2
echo "gt_lt_fp32 done"
python3 examples/runner.py --kernel ThreeColANDKernel --output_dir ./traces/imdb_three_col_and   --skip_functional_sim --arg 64
echo "three_col_and done"
```

핵심 포인트:

* `export PAGE_SHIFT=12`
  → 페이지 크기를 4KB로 설정.
* `--arg` 값은 각 kernel의 **input size 스케일**로 사용된다.

  * 예: `LtINT64Kernel(scale=1)`, `ThreeColANDKernel(scale=64)` 등.
  * TLB가 커버하는 범위보다 큰 워킹셋을 만들기 위해 scale을 키운다.
  * 이렇게 해서 DRAM-TLB/ATS/PRI 부하가 충분히 발생하도록 유도한다.

### 1.2 `examples/runner.py` – Kernel 객체 생성과 trace 파일 생성

핵심 부분:

```python
from benchmarks.imdb_lt_INT64 import LtINT64Kernel
# ...

def get_kernel(kernel_name, num_m2ndps=1, arg=-1) :
    kernel = getattr(sys.modules[__name__], kernel_name)
    if arg != -1:
        return kernel(arg)
    else:
        return kernel()

# ...

kernel = get_kernel(args.kernel, args.num_m2ndps, args.arg)
kernel_code = kernel.make_kernel()
input_map  = []
output_map = []
kernel_info = []

if args.num_m2ndps == 1:
    input_map.append(kernel.make_input_map())
    kernel_info.append(kernel.get_kernel_info())
    output_map.append(kernel.make_output_map())
    make_input_files(kernel.kernel_name, kernel_code, input_map[0],
                     output_map[0], kernel_info[0],
                     file_dir=os.path.join(args.output_dir, str(0)))
```

동작 요약:

1. `LtINT64Kernel(scale)` 같은 kernel 클래스를 생성한다.
2. `make_kernel()` → 커널 ISA 텍스트 생성 (`*.traceg`).
3. `make_input_map()`, `make_output_map()`
   → 메모리 맵 생성 (`*_input.data`, `*_output.data`).
4. `get_kernel_info()` → `base_addr`, `size`, `args` 등 launch 정보 생성 (`launch.txt`).
5. `make_input_files()` 가 위 네 가지를 해당 디렉토리에 저장한다.

---

## 2. 예시: `LtINT64Kernel` – Input scaling과 ISA

### 2.1 Input scaling

```python
class LtINT64Kernel(NdpKernel):
    def __init__(self, scale: int = 1):
        super().__init__()
        self.packet_size = 64
        self.int64_size  = 8

        BASE = 6001664
        self.input_size = int(BASE * int(scale))

        self.predicate_value = np.int64(5)
        self.input_a_addr = 0x800000000000
        self.output_addr  = 0x820000000000

        self.sync       = 0
        self.kernel_id  = 0
        self.kernel_name = 'lt_int64'
        self.base_addr   = self.input_a_addr
        self.bound       = self.input_size * self.int64_size

        # 입력 데이터
        self.input_a = np.random.randint(
            low=1, high=10, size=(self.input_size, 1), dtype=np.int64
        )

        # 출력 비트맵 (정답)
        self.output = np.where((self.input_a < self.predicate_value), 1, 0)
        self.output = self.output.reshape(-1, 8)
        self.output = np.flip(self.output, axis=1)
        self.output = np.packbits(self.output, axis=-1)
        self.output = self.output.reshape(-1).astype(np.uint8)

        # launch 인자: [output_addr, predicate_value]
        self.input_addrs = [self.output_addr, self.predicate_value]
```

중요한 부분:

* `BASE = 6001664`, `self.input_size = BASE * scale`

  * `scale` 값으로 워킹셋 크기를 선형적으로 키운다.
  * TLB의 커버 가능 메모리보다 크게 만들기 위해 사용한다.
* `self.output`

  * `(input_a < predicate_value)` 조건에 대한 **정답 비트맵**.
  * `*_output.data` 의 마지막 `uint8` 블록으로 들어가며,
    시뮬레이터 실행 후 `HashMemoryMap::Match()` 에서 결과 검증에 사용된다.

### 2.2 Kernel ISA (`make_kernel()`)

```python
def make_kernel(self):
    spad_addr = configs.spad_addr
    template  = ''
    template += f'-kernel name = {self.kernel_name}\n'
    template += f'-kernel id = {self.kernel_id}\n'
    template += '\n'
    template += f'KERNELBODY:\n'
    template += f'vsetvli t0, a0, e64, m1\n'
    template += f'vle64.v v1, x1\n'
    template += f'li x7, {spad_addr}\n'
    template += f'vle64.v v4, (x7)\n'
    template += f'vmv.x.s x3, v4\n'  # x3 = output_addr
    template += f'csrwi vstart, 1\n'
    template += f'vmv.x.s x4, v4\n'  # x4 = predicate_value
    template += f'vmslt.vx v2, v1, x4\n'
    template += f'srli x5, x2, 6\n'
    template += f'add x6, x3, x5\n'
    template += f'vsetvli t0, a0, e8, m1\n'
    template += f'vmv.x.s x3, v2\n'
    template += f'sb x3, (x6)\n'
    return template
```

* Scratchpad(`spad_addr`)에는 `output_addr`, `predicate_value` 가 argument로 저장된다.
* `vle64.v v1, x1` : μthread가 담당하는 input chunk를 load.
* `vmslt.vx v2, v1, x4` : `< predicate_value` 비교 결과를 vector mask로 생성.
* `srli x5, x2, 6` / `add x6, x3, x5` : μthread offset 기준으로 output bitmap byte 위치 계산.
* `sb x3, (x6)` : 해당 byte에 mask를 저장.

`template` 문자열 전체가 `lt_int64.traceg` 로 저장되고
NDP 시뮬레이터는 이를 파싱하여 μthread instruction stream으로 사용한다.

---

## 3. Trace 파일 포맷 (`*.traceg`, `*_input.data`, `*_output.data`, `launch.txt`)

### 3.1 `kernelslist.g`와 `*.traceg`

* `kernelslist.g` 예:

  ```text
  lt_int64
  ```
* `lt_int64.traceg` 예:

  ```text
  -kernel name = lt_int64
  -kernel id = 0

  KERNELBODY:
  vsetvli t0, a0, e64, m1
  vle64.v v1, x1
  li x7, 1152921504606846976
  vle64.v v4, (x7)
  vmv.x.s x3, v4
  csrwi vstart, 1
  vmv.x.s x4, v4
  vmslt.vx v2, v1, x4
  srli x5, x2, 6
  add x6, x3, x5
  vsetvli t0, a0, e8, m1
  vmv.x.s x3, v2
  sb x3, (x6)
  ```

### 3.2 `*_input.data`

예: `lt_int64_input.data`

```text
META
int64
DATA
0x800000000000 8 4 4 7 4 6 2 5
0x800000000040 5 4 5 7 4 6 9 8
0x800000000080 5 9 4 5 3 9 6 9
...
```

* `META` 다음 줄: 데이터 타입 (`int64`, `float32`, `uint8`, …).
* `DATA` 이후 각 줄:

  * 첫 토큰: 64B aligned packet base 주소.
  * 이후 토큰: 해당 packet의 실제 데이터 값들.

### 3.3 `*_output.data`

예: `lt_int64_output.data`

앞부분은 input과 동일한 데이터가 들어 있고, 그 뒤에 정답 output 영역이 붙는다.

```text
# 앞부분: input과 동일한 구간
0x80000895df40 7 7 5 8 9 4 3 5
...

META
uint8
DATA
0x820000000000 86 18 20 141 85 230 77 156 ...
0x820000000040 115 2 102 213 ...
...
```

* 마지막 `META / uint8 / DATA` 블록: 정답 비트맵.
* 시뮬레이션 결과 역시 같은 주소 범위에 `uint8` 값들이 기록되어야 하고,
  `HashMemoryMap::Match()`에서 이 값을 기준으로 correctness를 검증한다.

### 3.4 `launch.txt`

예:

```text
0 0 0x800000000000 0x895e000 0x10 0x10 0x820000000000 0x5
```

각 필드는 내부적으로 `KernelLaunchInfo` 구조체로 파싱되어

* μthread pool region의 base 주소 / size
* output 주소
* kernel argument (`output_addr`, `predicate_value` 등)

로 사용된다. 파싱은 `M2NDPParser::parse_kernel_launch()` 에서 수행한다.

---

## 4. Timing Simulator 주요 컴포넌트

이 절의 내용은 **Timing 모드**에 해당하는 코드들이다
(`TIMING_SIMULATION` 매크로 기준).

### 4.1 `HashMemoryMap` – 메모리 이미지 관리

`memory_map.cc` 에서 `*_input.data`, `*_output.data` 파일을 읽어
`addr_base → VectorData` 형태로 저장한다.

```cpp
if (meta_read) {
  std::stringstream ss(line);
  std::string tmp;
  ss >> tmp;
  if (tmp == "float32")      meta_type = DataType::FLOAT32;
  else if (tmp == "int64")   meta_type = DataType::INT64;
  else if (tmp == "uint8")   meta_type = DataType::UINT8;
  // ...
} else {
  uint64_t addr_base;
  std::stringstream ss(line);
  ss >> std::hex >> addr_base;
  assert(addr_base != 0);
  assert(addr_base % PACKET_SIZE == 0);

  VectorData input_data64(64, 1);
  VectorData input_data8(8, 1);
  input_data64.SetType(meta_type);
  input_data8.SetType(meta_type);

  // 주석 처리된 부분에서 ss >> 값들을 읽어서 SetData(...) 호출
  // ...

  if (meta_type == CHAR8 || meta_type == UINT8 || meta_type == BOOL)
    m_data_map[addr_base] = input_data8;
  else if (meta_type == INT64)
    m_data_map[addr_base] = input_data64;
  // ...
}
```

* `Load(addr)`
  → 해당 주소가 속한 packet base를 찾아 해당 `VectorData` 를 반환.
* `Store(addr, data)`
  → 해당 base 주소에 대해 `VectorData` 를 저장/갱신.
* `Match(other)`
  → golden output(`*_output.data`)과 실제 결과를 비교하여 correctness를 판단.

Timing 모드에서도 실제 데이터는 여전히 `HashMemoryMap`에 있고,
TLB/캐시/DRAM 코드는 해당 주소 접근에 latency와 bandwidth 제약을 모델링한다.

### 4.2 `mem_fetch` – 메모리 요청 단위

`mem_fetch`는 NDP 유닛에서 메모리 계층으로 나가는 단일 요청을 표현한다.

```cpp
mem_fetch::mem_fetch(new_addr_type addr, mem_access_type acc_type, mf_type type,
                     unsigned data_size, unsigned ctrl_size,
                     unsigned long long timestamp)
    : m_addr(addr),
      m_mem_access_type(acc_type),
      m_type(type),
      m_data_size(data_size),
      m_ctrl_size(ctrl_size),
      m_timestamp(timestamp) {
  m_request_id = unique_uid++;
  m_sector_mask.set(addr % (MAX_MEMORY_ACCESS_SIZE) / MEM_ACCESS_SIZE);
  m_valid = true;
  m_src_id = 0;
  m_atomic = false;
}
```

* `m_type` : `READ_REQUEST`, `READ_REPLY`, `WRITE_REQUEST`, `WRITE_ACK` 등.
* `set_reply()`에서

  ```cpp
  if (m_type == mf_type::READ_REQUEST)
    m_type = mf_type::READ_REPLY;
  else if (m_type == mf_type::WRITE_REQUEST)
    m_type = mf_type::WRITE_ACK;
  ```

  처럼 요청이 응답 타입으로 전환된다.

이 객체는 TLB, L1/L2 cache, DRAM, CXL 링크 사이를 공통 인터페이스로 이동하며,
각 단계에서 latency와 상태 전이를 기록한다.

### 4.3 `NdpUnit` – Timing pipeline 상위 구조

Timing 모드에서 `NdpUnit::cycle()` 은 다음과 같은 순서를 따른다.

```cpp
void NdpUnit::cycle() {
  handle_finished_context();
  rf_writeback();
  from_mem_handle();
  l1_inst_cache_cycle();
  to_l1_inst_cache();
  tlb_cycle();
  m_ldst_unit->cycle();
  connect_to_ldst_unit();

  bool inst_queue_empty = true;
  for (int i = 0; i < m_num_sub_core; i++) {
    m_sub_core_units[i]->cycle();
    inst_queue_empty = inst_queue_empty && m_sub_core_units[i]->is_inst_queue_empty();
  }
  if (inst_queue_empty && m_config->is_coarse_grained()) {
    m_uthread_generator->generate_uthreads(
        m_config->get_uthread_slots() * m_num_sub_core);
  }

  connect_instruction_buffer_to_sub_core();
  request_instruction_lookup();

  m_uthread_generator->cycle();
  m_instruction_buffer->cycle();
  m_ndp_cycles++;
  m_stats->inc_cycle();
}
```

요약:

* `SubCore::cycle()` 에서 μthread 단위로 instruction을 실행하고,
  load/store instruction에 대해 메모리 요청을 만든다.
* load/store 요청은 `m_to_ldst_unit`/`m_to_v_ldst_unit` 등을 거쳐 `LDSTUnit`으로 전달된다.
* `LDSTUnit`은 DTLB, L1D, L2, DRAM, CXL link로 이어지는 경로를 따라가도록 `mem_fetch`를 발행한다.
* 이 과정에서 TLB가 address translation latency를 추가하며,
  그 구현이 다음 장([5. TLB 확장 구현](#5-tlb-확장-구현-이-연구에서-추가한-부분))에 있다.

---

## 5. TLB 확장 구현 (이 연구에서 추가한 부분)

이 절부터는 **원래 코드에 추가/수정된 TLB 관련 구현**만 다룬다.

### 5.1 목표

추가 구현의 목적은 다음과 같다.

1. on-chip TLB miss 시 단순 고정 latency가 아니라,

   * DRAM-TLB(또는 shadow page table) probe,
   * ATS 요청,
   * PRI 요청
     을 구분해서 나타내도록 latency를 모델링.
2. Page-table 변경이 발생하는 상황을 주소(VPN) 기반 확률 모델로 도입.
3. DRAM-TLB probe, ATS, PRI 등 다양한 latency가 섞여 있어도

   * 먼저 끝나는 이벤트가 먼저 처리되도록
   * FIFO 대신 **min-heap 기반 DelayQueue** 사용.

### 5.2 파라미터 정의 (`tlb.h`)

```cpp
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
// ppm 단위 (예: 50000 → 5%)
#ifndef CHANGE_PPM
#define CHANGE_PPM 50000
#endif

#ifndef CHANGE_PERIOD_CYCLES
#define CHANGE_PERIOD_CYCLES 1107
#endif

// DRAM-TLB 지연큐 처리량
#ifndef DRAM_TLB_DEQUEUE_PER_CYCLE
#define DRAM_TLB_DEQUEUE_PER_CYCLE 8
#endif
```

* `PROBE_CYCLES`: DRAM-TLB / shadow page table 접근 비용.
* `ATS_CYCLES`: ATS 트랜잭션 지연.
* `PRI_CYCLES`: PRI 트랜잭션 지연.
* `CHANGE_PPM`: 특정 epoch에서 “page-table 변경이 걸린 VPN”의 비율(1e6 분모).
* `CHANGE_PERIOD_CYCLES`: 일정 주기마다 VPN 집합 변경을 위한 salt 갱신 주기.
* `DRAM_TLB_DEQUEUE_PER_CYCLE`: 한 사이클에 DRAM-TLB latency queue에서 처리 가능한 entry 수.

### 5.3 DelayQueue – min-heap 기반 지연 큐

여러 종류의 latency(Probe, ATS, PRI)가 섞인 상황에서,
**완료 예정 시각(ready_cycle)이 가장 빠른 이벤트가 먼저 처리되도록** 하기 위해
기존 FIFO 큐 대신 priority queue(min-heap)로 구현했다.

`delay_queue.h`:

```cpp
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

  void push(T data, int delay);
  void push(T data, int delay, int interval);
  void pop();
  T top();

  int  size()  const { return m_size; }
  bool empty() const;        // ready 여부 기준
  bool queue_empty() const;  // heap 실제 비어있는지 여부
  bool full();

  void cycle();

 private:
  struct QueueEntry {
    T        data;
    uint64_t ready_cycle;
    uint64_t seq;           // 같은 ready_cycle이면 입력 순서 유지
  };
  struct Cmp {
    bool operator()(const QueueEntry& a, const QueueEntry& b) const {
      if (a.ready_cycle != b.ready_cycle) return a.ready_cycle > b.ready_cycle; // min-heap
      return a.seq > b.seq;
    }
  };

  std::priority_queue<QueueEntry, std::vector<QueueEntry>, Cmp> m_heap;
  // ...
};
```

`delay_queue.cc` 의 `push` 구현:

```cpp
template <typename T>
void DelayQueue<T>::push(T data, int delay) {
  assert(m_only_latency);
  m_size++;
  m_heap.push(typename DelayQueue<T>::QueueEntry{
      data, m_cycle + (uint64_t)delay, m_seq++
  });
}
```

* 각 entry는 `(data, ready_cycle, seq)`를 가진다.
* `cycle()`에서 `m_cycle`이 증가하고,
  `ready_cycle <= m_cycle` 이 되는 순간 `empty() == false`가 된다.
* 이때 `top()`으로 가장 먼저 끝나는 이벤트부터 꺼낼 수 있고,
  예를 들어 PRI(32000 cycles)가 먼저 들어가 있었더라도
  나중에 들어온 Probe(560 cycles)가 먼저 완료되면 그쪽이 먼저 처리된다.

### 5.4 Page-table change 확률 모델링 (`change_pick()`)

Page-table 업데이트는 실제 HW에서 OS/host에 의해 일어나지만,
여기서는 **VPN 기반 pseudo-random 서브셋 선택**으로 모델링한다.

```cpp
// 주기적으로 change salt 갱신
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
  // SplitMix64 해시
  x += 0x9e3779b97f4a7c15ULL;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
  x = x ^ (x >> 31);

  return (x % 1000000ULL) < (uint64_t)CHANGE_PPM;
}
```

예를 들면,

* `x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;` 라인은 SplitMix64 알고리즘의 한 단계로,
  `(vpn ^ salt)` 값의 비트를 섞어서 상·하위 비트에 randomness를 균등하게 퍼뜨리는 부분이다.
* 최종적으로 `x % 1_000_000 < CHANGE_PPM` 조건으로
  “현재 epoch에서 이 VPN이 page-table change가 걸린 상태인지” 를 결정한다.
* `maybe_advance_change()`에서 `CHANGE_PERIOD_CYCLES`마다 `s_change_salt` 를 증가시키므로,
  시간이 지나면서 어떤 VPN이 change 대상인지가 바뀐다.

### 5.5 TLB miss 처리 경로: DRAM-TLB + ATS/PRI 지연 (`fill()`)

on-chip TLB miss 후 DRAM-TLB 또는 shadow page table을 보는 과정에서
Probe/ATS/PRI latency를 합산해서 모델링한다.

```cpp
void Tlb::fill(mem_fetch* mf) {
  mf->current_state = "TLB Fill";

  // 원 요청 주소(VPN) 기준으로 page-table change 여부 판단
  mem_fetch* orig = mf->get_tlb_original_mf();
  const uint64_t orig_addr = orig ? orig->get_addr() : 0;
  const uint64_t vpn = vpn_of(orig_addr, (uint64_t)m_page_size);

  // 기본 DRAM-TLB probe 비용
  int delay = PROBE_CYCLES;

  // change가 걸린 VPN이면 ATS/PRI 부과
  if (change_pick(vpn)) {
    const bool is_wr = is_write_req(mf);
    delay += is_wr ? PRI_CYCLES : ATS_CYCLES;
  }

  // DRAM-TLB 존재 집합 관리용: 접근한 tlb_addr 등록
  const uint64_t tlb_addr = mf->get_addr();
  m_accessed_tlb_addr->insert(tlb_addr);

  // 지연 큐에 push → 만료 시 bank_access_cycle()에서 on-chip TLB fill
  m_dram_tlb_latency_queue.push(mf, delay);
}
```

해석:

* on-chip TLB miss → DRAM-TLB 상의 entry를 읽어온다고 가정.
* 항상 최소 `PROBE_CYCLES` 는 들어간다.
* `change_pick(vpn)` 이 true이면,

  * read 요청: ATS latency (`ATS_CYCLES`) 추가,
  * write 요청: NDP가 page에 대해 첫 쓰기라고 간주하고 PRI latency (`PRI_CYCLES`) 추가.
* 실제 프로토콜(ATS 실패→PRI→ATS 재시도)은 단순화해서 고정 지연값 하나로 처리했다.

### 5.6 DRAM-TLB 지연 완료 후 on-chip TLB fill (`bank_access_cycle()`)

```cpp
void Tlb::bank_access_cycle() {
  // (1) Probe/ATS/PRI 지연 완료 → on-chip TLB fill
  for (int i = 0; i < DRAM_TLB_DEQUEUE_PER_CYCLE; ++i) {
    if (m_dram_tlb_latency_queue.empty()) break;
    mem_fetch* mf = m_dram_tlb_latency_queue.top();
    m_tlb->fill(mf, m_config->get_ndp_cycle());
    m_dram_tlb_latency_queue.pop();
  }

  // (2) on-chip TLB access 완료 → 원 요청 완료
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
```

순서:

1. DRAM-TLB latency queue(`m_dram_tlb_latency_queue`)에서
   ready된 항목을 최대 `DRAM_TLB_DEQUEUE_PER_CYCLE` 개까지 꺼내
   on-chip TLB (`m_tlb`)에 `fill()` 한다.
2. on-chip TLB 내부에서 access가 끝난 mem_fetch 들은
   `m_finished_mf` 큐로 이동하며, 원 요청(`get_tlb_original_mf()`)을 깨운다.
3. on-chip TLB lookup은 `m_tlb_request_queue` 에 쌓여 있고,
   `get_tlb_addr()` 로 DRAM-TLB 상의 주소를 계산한 뒤
   별도의 `tlb_mf` 를 만들어 DRAM 방향으로 보낸다.

### 5.7 `cycle()` – change salt 갱신 포함

```cpp
void Tlb::cycle() {
  m_tlb->cycle();
  m_tlb_request_queue.cycle();
  m_dram_tlb_latency_queue.cycle();

  maybe_advance_change(m_config->get_ndp_cycle());
}
```

* DelayQueue 두 개(`m_tlb_request_queue`, `m_dram_tlb_latency_queue`)는
  내부적으로 `m_cycle` 을 증가시키며 ready 상태를 업데이트한다.
* `maybe_advance_change()`에서
  `CHANGE_PERIOD_CYCLES`마다 `s_change_salt`를 변경해
  시간에 따라 page-table change가 걸리는 VPN 집합이 이동하도록 만든다.

---

## 6. 요약 및 실험 시 유용한 포인트

### 6.1 실험 시 자주 손댈 수 있는 부분

* **워킹셋 크기 / 페이지 크기**

  * `make_trace.sh` 의 `--arg` 값 (scale factor)
  * `PAGE_SHIFT` (페이지 크기)
* **TLB/ATS/PRI latency**

  * `tlb.h` 의 `PROBE_CYCLES`, `ATS_CYCLES`, `PRI_CYCLES`
* **page-table 변화 비율**

  * `CHANGE_PPM`, `CHANGE_PERIOD_CYCLES`
* **DRAM-TLB 처리량**

  * `DRAM_TLB_DEQUEUE_PER_CYCLE`

### 6.2 TLB 관련 코드 위치 정리

* `tlb.h`, `tlb.cc`
  → DRAM-TLB, ATS/PRI, page-table change 확률 모델이 구현되어 있는 핵심 파일.
* `delay_queue.h`, `delay_queue.cc`
  → min-heap 기반 DelayQueue 구현.
* `mem_fetch.h`, `mem_fetch.cc`
  → 메모리 요청 단위 구조체 및 타입 전환(`set_reply()`) 등.
* `ndp_unit.cc`

  * `tlb_cycle()`, `from_mem_handle()`, `cycle()`
    → TLB와 NDP unit 간 연결 경로 및 전체 pipeline 내에서의 위치를 이해하는 데 필요.

### 6.3 전체 흐름 정리

1. Python 코드가 trace, 메모리 이미지, launch 정보를 생성한다.
2. C++ 시뮬레이터가 이를 읽어 `HashMemoryMap` 에 데이터를 올린다.
3. `NdpUnit` / `SubCore` 가 μthread 단위로 커널을 실행하면서 load/store를 발생시킨다.
4. `mem_fetch`가 TLB, cache, DRAM, CXL 경로를 거치면서 cycle 기반 timing simulation이 진행된다.
5. TLB 확장 구현(Probe/ATS/PRI + page-table change + DelayQueue)이
   address translation 단계 latency를 조절한다.
6. 실행 후 `HashMemoryMap::Match()`로 결과를 golden output과 비교해 correctness를 확인한다.




