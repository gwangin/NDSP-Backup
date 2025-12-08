#!/usr/bin/env python3
import os, pathlib, time, signal
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, expr, broadcast
from pyspark.sql.window import Window
from pyspark.sql.functions import row_number
from pyspark import StorageLevel

PARQUET_DIR = os.environ.get("OLAP_PARQUET_DIR","file:///home/gwangin/spark/olap/parquet_uncompressed")
PID_DIR = pathlib.Path(os.environ.get("SPARK_PID_DIR", str(pathlib.Path.home()/ "spark" / "pids")))
PID_DIR.mkdir(parents=True, exist_ok=True)
(PID_DIR / "olap_driver_python.pid").write_text(str(os.getpid()))

WORK_SECS = float(os.environ.get("WORK_SECS", "3600"))
WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "4"))
CACHE_REFRESH_SEC = int(os.environ.get("CACHE_REFRESH_SEC", "1800"))
SLEEP_SEC = int(os.environ.get("SLEEP_SEC", "10"))
TOPN_PER_BUCKET = int(os.environ.get("TOPN_PER_BUCKET", "20000"))
BUCKETS = int(os.environ.get("BUCKETS", "256"))
DIM_UPDATE_EVERY = int(os.environ.get("DIM_UPDATE_EVERY", "300"))

spark = (SparkSession.builder
  .appName("OLAP-Filter-SnapshotPT")
  .config("spark.sql.parquet.enableVectorizedReader","true")
  .config("spark.sql.files.maxPartitionBytes","67108864")
  .config("spark.sql.adaptive.enabled","true")
  .config("spark.sql.adaptive.coalescePartitions.enabled","true")
  .config("spark.sql.shuffle.partitions", str(BUCKETS))
  .config("spark.memory.offHeap.enabled","true")
  .config("spark.memory.offHeap.size","2g")
  .config("spark.network.io.preferDirectBufs","true")
  .config("spark.shuffle.io.preferDirectBufs","true")
  .config("spark.sql.columnVector.offheap.enabled","true")
  .config("spark.eventLog.enabled","true")
  .config("spark.eventLog.dir","file:///home/gwangin/spark/eventlogs")
  .config("spark.driver.extraJavaOptions",
          "-XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+ExplicitGCInvokesConcurrent")
  .getOrCreate())

# JVM PID 기록
try:
  jvm = spark._jvm
  name = jvm.java.lang.management.ManagementFactory.getRuntimeMXBean().getName()
  java_pid = int(str(name).split("@", 1)[0])
  (PID_DIR / "olap_driver_java.pid").write_text(str(java_pid))
except Exception:
  pass

base = spark.read.parquet(PARQUET_DIR)

has_event_time = "event_time" in base.columns
if has_event_time:
  fact = base.where(expr(f"event_time >= current_timestamp() - interval {WINDOW_HOURS} hours"))
else:
  fact = base

fact = fact.repartition(BUCKETS, (col("category") % BUCKETS)).persist(StorageLevel.MEMORY_AND_DISK)
fact.count()  # warm-up

dim = (fact.select((col("category") % 1024).alias("dk"), col("flag").alias("flag_d"))
           .dropDuplicates(["dk"])
           .persist(StorageLevel.MEMORY_ONLY))
dim.count()

_running = True
def _stop(signum, frame):
  global _running
  _running = False
for s in (signal.SIGINT, signal.SIGTERM):
  signal.signal(s, _stop)

t0 = time.time()
k = 0
last_cache_refresh = time.time()
last_dim_update = time.time()

def time_ok():
  if WORK_SECS < 0: return True
  return (time.time() - t0) < WORK_SECS

while _running and time_ok():
  seg = k % 8
  dfL = fact.where( (col("category") % 8) == seg ).withColumn("dk", (col("category") % 1024))

  now = time.time()
  if now - last_dim_update > DIM_UPDATE_EVERY:
    dim.unpersist(blocking=False)
    dim = (fact.select((col("category") % 1024).alias("dk"), col("flag").alias("flag_d"))
              .dropDuplicates(["dk"])
              .persist(StorageLevel.MEMORY_ONLY))
    dim.count()
    last_dim_update = now

  jn = dfL.join(broadcast(dim), on="dk", how="left")

  agg = jn.groupBy((col("category") % BUCKETS).alias("g")) \
          .agg(expr("avg(price) as ap"), expr("sum(qty) as sq"))
  agg.count()

  # Top-N (정상 Window API 사용)
  w = Window.partitionBy((col("category") % BUCKETS)).orderBy(col("price").desc())
  per_bucket_n = max(1, TOPN_PER_BUCKET // BUCKETS)
  topk = (jn.select("category","price","qty")
            .withColumn("rn", row_number().over(w))
            .where(col("rn") <= per_bucket_n))
  topk.count()

  thr = 50.0 + (k % 50)
  sel = jn.where((col("price") > thr) & (col("qty") < (10 + (k % 40))) & col("flag"))
  sel.count()

  if now - last_cache_refresh > CACHE_REFRESH_SEC:
    fact.unpersist(blocking=False)
    base = spark.read.parquet(PARQUET_DIR)
    if has_event_time:
      fact = base.where(expr(f"event_time >= current_timestamp() - interval {WINDOW_HOURS} hours"))
    else:
      fact = base
    fact = fact.repartition(BUCKETS, (col("category") % BUCKETS)).persist(StorageLevel.MEMORY_AND_DISK)
    fact.count()
    last_cache_refresh = now

  k += 1
  time.sleep(SLEEP_SEC)

spark.stop()
