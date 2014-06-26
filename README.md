yperf
=====

Simple performance monitor for Linux with report summary to inspect
performance of multi-step distributed systems.

yperf.py
-------
The yperf.py monitor should be continously run on all host machines of 
a distributed frameworks such as snapworld to
record total cpu, disk, and network performance each second.

gen_report.py
-------
As input, takes in a json file such as

```
{
    "hosts":[
       {
          "host":"101.39.18.12",
          "port":"9200",
          "id":"1"
       },
       {
          "host":"101.39.18.9",
          "port":"9200",
          "id":"2"
       },
       {
          "host":"101.39.18.10",
          "port":"9200",
          "id":"3"
       },
       {
          "host":"101.39.18.1",
          "port":"9200",
          "id":"4"
       }
    ],
   "meta_data": {"whatever": "Can be anything"},
   "run_name":"snapworld-1B-run",
   "step_times":[
      1391626150
      1391626372,
      1391626376,
      1391626377,
      1391626387,
      1391626388,
      1391626418,
      1391626419
   ]
}
```
The step_times are epoch timestamps, with step_times[0] representing when the entire
computation started, step_times[1] when the first step finished, etc. It will then
create and deploy tables and graphs summarrizing the performance during each step
similar to http://snapworld.stanford.edu/metrics/metrics-20140205-104910/
