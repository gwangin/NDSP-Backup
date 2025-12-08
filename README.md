# 공부해야할 것 List

**여기 제시된 논문,링크 이외에도 스스로 자료를 찾아서 해당 개념에 대해 이해해야함.**

* CXL 자체에 대한 공부 (이건 꾸준히 하기)
    * spec 최신 버전 다운로드 받고 2, 3, 7, Appendix을 필수로 읽기.
    * dax가 무엇인지 이해하기 https://docs.kernel.org/filesystems/dax.html
* 기존 GPU, 가속기도 CPU와 가속기의 core가 virtual address를 공유,통합 하려는 시도는 있어왔다. ex) SVM, UVM 그렇다면 기존 방식과 CXL memory에서의 NDP core는 무엇이 다른지 이해해야함.
    * SVA/SVM  Shared Virtual Address와 Shared Virtual Memory
        * Shared Virtual Memory: Its Design and Performance Implications for Diverse Applications- https://arxiv.org/pdf/2405.06811
        * In-Depth Analyses of Unified Virtual Memory System for GPU Accelerated Computing
    * UVM (Unified Virtual Memory)
        * NVIDIA 공식 문서들을 검색해서 참고.
        * GPUVM: GPU-driven Unified Virtual Memory - https://arxiv.org/pdf/2411.05309
        * 위 환경에서 GPU page table과 CPU page table의 상태가 CXL NDP memory와 어떻게 다른지 파악하기



* ATS / PRI (Address Translation Service / Page Request Interface)  그리고 IOMMU 공부하기
    * IOMMU 공부 
        *  https://pages.cs.wisc.edu/~basu/isca_iommu_tutorial/IOMMU_TUTORIAL_ASPLOS_2016.pdf
        * rIOMMU: Efficient IOMMU for I/O Devices that Employ Ring Buffers 논문
    * VPRI: Efficient I/O page fault handling via software-hardware Co-design for IaaS clouds- https://dl.acm.org/doi/10.1145/3694715.3695957
    * To PRI or Not PRI, That's the question - https://www.usenix.org/conference/osdi25/presentation/wang-yun
* Linux HMM
    * https://www.kernel.org/doc/html/v5.0/vm/hmm.html
    * https://docs.kernel.org/mm/mmu_notifier.html




## CODE 백업

### Page table이 변하는 Application을 찾기.

Page table이 변하는 application을 찾기 위해서 Pagemap snapshot을 찍어 각 스냅샷끼리 비교하는 방법을 사용함.
/proc/<pid>/pagemap
pagemap은 Linux 커널이 “각 프로세스의 가상주소(VA)가 어떤 물리 페이지(PFN)에 매핑돼 있는지”를 사용자 공간에 제공하는 인터페이스

각 어플리케이션의 PTE변화를 측정하는 실험 방법은 GPT를 활용하여 만들어도 잘 만들어줌
5초마다 pagemap snapshot을 기록하고, 기록할 때마다 직전 스냅샷과 비교하여 아래 3가지를 기록해야함.

1. 새로 생긴 PTE,
2. VPN은 그대로인데 PFN이 변한 PTE,
3. 제거된 PTE
   
***만약 백업된 코드와 스크립트가 이해 안되면 다시 만드는게 편할 수도 있음.***


### redis 실험
#### 백업 파일 설명
* snap_pagetable.py
    * /proc/<pid>/pagemap 읽어서 vpn,status,pfn 등의 PTE정보를 CSV로 저장 → Snapshot을 만듦
* capture_loop.sh
    * Snap_pagetable.py를 주기적으로 호출해서 pt_ epoch 생성
    * 각 스냅샷 후 append_last_ diff. py 실행
* start_capture.sh
    * capture_loop.sh를 백그라운드로 실행
* diff_pagetable.py
    * 스냅샷 두개에서 page table의 변화(added, changed, removed) 계산
* analyze_diff.py
    * snapshot 전체를 순회하면서 연속 pair마다 diff_pagetable.py 호출
    * 실험 끝난 뒤 한번 돌려 전체 diff 세트를 만드는 스크립트


* 실험 방법
  
***모든 실험은 Application 동작과 상관없이 Page table을 변경시킬 수 있는 OS 옵션안 AutoNUMA, THP 등을  끄고 해야함.***
```
cd ~/KVStore/pt_capture
PORT=6380 ENABLE_COW=0 RUN_FOR_SECS=600 THREADS=32 CAP_INTERVAL=5 ./run_two_phase.sh
```

* 실험 완료 후 생성되는 결과
   * snapshots/pt_*.csv.gz # pagemap 스냅샷들
   * diffs/stream_summary.csv # 5초 단위 added/changed/removed/RSS 요약
   * diffs/stream_totals.txt # 전체 누적 PT 변화량
   * logs/capture.log # 캡처 과정 실시간 로그

### spark 실험
#### 백업파일 설명
* env.sh
    * Spark 실행환경 설정(SPARK_HOME 찾기)
* olap_app.py
    * Spark OLAP workload 실행 + PID 기록
* start_olap_ with_ capture.sh
    * Spark 실행 → JVM PID 획득 → capture 루프 시작
* snap_pagetable.py
    * 프로세스 pagemap 읽어 스냅샷 생성
* diff_pagetable.p
    * 스냅샷 간 added/changed/removed 계산
* append_change_ log.py
    * diff 결과 + RSS 값을 로그 파일에 한 줄 기록
* capture_ loop.sh
    * PID 살아있는 동안 주기적으로 스냅샷 + diff 기록

      
 * 실험 방법
   

***모든 실험은 Application 동작과 상관없이 Page table을 변경시킬 수 있는 OS 옵션안 AutoNUMA, THP 등을  끄고 해야함.***

   ```cd ~/spark/olap_snapshot_pt
   source env.sh
   echo "$SPARK_HOME"
   which spark-submit
   ./start_olap_with_capture.sh 8g 50 5
   종료 후 log/pt_changes.log 확인
   ```
   




