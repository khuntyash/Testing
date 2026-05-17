# Capacity Worksheet

Use this worksheet weekly to tune worker count and budget.

## Inputs

- Daily labels processed
- Average OCR+crop seconds per label
- Peak multiplier (default 3x)
- Worker vCPU per instance
- Target max queue wait (seconds)

## Formula

- `daily_cpu_seconds = labels_per_day * sec_per_label`
- `avg_cpu_cores = daily_cpu_seconds / 86400`
- `peak_cpu_cores = avg_cpu_cores * peak_multiplier`
- `worker_instances = ceil(peak_cpu_cores / vcpu_per_worker)`

## Example (30k/day, 0.8 sec/label, peak 3x, 8 vCPU workers)

- `daily_cpu_seconds = 30000 * 0.8 = 24000`
- `avg_cpu_cores = 24000 / 86400 = 0.28`
- `peak_cpu_cores = 0.28 * 3 = 0.84`
- `worker_instances = ceil(0.84 / 8) = 1`

Real-world overhead (I/O, retries, mixed jobs) typically needs 2-3x this baseline.

## Autoscaling trigger defaults

- Scale up:
  - queued > 500 for 10 min, or
  - oldest queued age > 180 sec
- Scale down:
  - queued < 50 for 30 min and CPU < 40%

