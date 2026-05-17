from __future__ import annotations

import argparse
import os

import boto3


def _build_alarm_name(service: str, suffix: str) -> str:
    return f"{service}-{suffix}".replace("/", "-")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure ECS worker autoscaling from queue pressure alarms.")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    parser.add_argument("--cluster", default=os.getenv("ECS_CLUSTER", "cropperhub-cluster"))
    parser.add_argument("--service", default=os.getenv("ECS_WORKER_SERVICE", "cropperhub-worker-svc"))
    parser.add_argument("--namespace", default=os.getenv("CW_QUEUE_NAMESPACE", "CropperHub/Queue"))
    parser.add_argument("--min-capacity", type=int, default=int(os.getenv("WORKER_MIN_CAPACITY", "4")))
    parser.add_argument("--max-capacity", type=int, default=int(os.getenv("WORKER_MAX_CAPACITY", "50")))
    parser.add_argument("--depth-up-threshold", type=int, default=int(os.getenv("QUEUE_DEPTH_SCALE_UP", "25")))
    parser.add_argument("--age-up-threshold", type=int, default=int(os.getenv("QUEUE_AGE_SCALE_UP_SEC", "120")))
    parser.add_argument("--depth-down-threshold", type=int, default=int(os.getenv("QUEUE_DEPTH_SCALE_DOWN", "4")))
    parser.add_argument("--scale-out-adjustment", type=int, default=int(os.getenv("SCALE_OUT_ADJUSTMENT", "2")))
    parser.add_argument("--scale-in-adjustment", type=int, default=int(os.getenv("SCALE_IN_ADJUSTMENT", "-1")))
    parser.add_argument("--scale-out-cooldown", type=int, default=int(os.getenv("SCALE_OUT_COOLDOWN_SEC", "120")))
    parser.add_argument("--scale-in-cooldown", type=int, default=int(os.getenv("SCALE_IN_COOLDOWN_SEC", "600")))
    args = parser.parse_args()

    resource_id = f"service/{args.cluster}/{args.service}"
    scalable = boto3.client("application-autoscaling", region_name=args.region)
    cloudwatch = boto3.client("cloudwatch", region_name=args.region)

    scalable.register_scalable_target(
        ServiceNamespace="ecs",
        ScalableDimension="ecs:service:DesiredCount",
        ResourceId=resource_id,
        MinCapacity=max(1, args.min_capacity),
        MaxCapacity=max(args.min_capacity, args.max_capacity),
    )

    scale_out = scalable.put_scaling_policy(
        PolicyName=f"{args.service}-queue-scale-out",
        ServiceNamespace="ecs",
        ScalableDimension="ecs:service:DesiredCount",
        ResourceId=resource_id,
        PolicyType="StepScaling",
        StepScalingPolicyConfiguration={
            "AdjustmentType": "ChangeInCapacity",
            "Cooldown": max(0, args.scale_out_cooldown),
            "MetricAggregationType": "Maximum",
            "StepAdjustments": [{"MetricIntervalLowerBound": 0.0, "ScalingAdjustment": max(1, args.scale_out_adjustment)}],
        },
    )
    scale_in = scalable.put_scaling_policy(
        PolicyName=f"{args.service}-queue-scale-in",
        ServiceNamespace="ecs",
        ScalableDimension="ecs:service:DesiredCount",
        ResourceId=resource_id,
        PolicyType="StepScaling",
        StepScalingPolicyConfiguration={
            "AdjustmentType": "ChangeInCapacity",
            "Cooldown": max(60, args.scale_in_cooldown),
            "MetricAggregationType": "Average",
            "StepAdjustments": [{"MetricIntervalUpperBound": 0.0, "ScalingAdjustment": min(-1, args.scale_in_adjustment)}],
        },
    )

    dimensions = [
        {"Name": "ClusterName", "Value": args.cluster},
        {"Name": "ServiceName", "Value": args.service},
    ]
    cloudwatch.put_metric_alarm(
        AlarmName=_build_alarm_name(args.service, "queue-depth-high"),
        AlarmDescription="Scale out workers when queue depth stays high.",
        Namespace=args.namespace,
        MetricName="QueuedDepth",
        Dimensions=dimensions,
        Statistic="Maximum",
        Period=60,
        EvaluationPeriods=2,
        Threshold=float(args.depth_up_threshold),
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[scale_out["PolicyARN"]],
    )
    cloudwatch.put_metric_alarm(
        AlarmName=_build_alarm_name(args.service, "queue-age-high"),
        AlarmDescription="Scale out workers when oldest queued task age grows.",
        Namespace=args.namespace,
        MetricName="OldestQueuedAgeSec",
        Dimensions=dimensions,
        Statistic="Maximum",
        Period=60,
        EvaluationPeriods=2,
        Threshold=float(args.age_up_threshold),
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[scale_out["PolicyARN"]],
    )
    cloudwatch.put_metric_alarm(
        AlarmName=_build_alarm_name(args.service, "queue-depth-low"),
        AlarmDescription="Scale in workers only after sustained low queue depth.",
        Namespace=args.namespace,
        MetricName="QueuedDepth",
        Dimensions=dimensions,
        Statistic="Average",
        Period=60,
        EvaluationPeriods=10,
        Threshold=float(args.depth_down_threshold),
        ComparisonOperator="LessThanThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[scale_in["PolicyARN"]],
    )

    print(
        "configured ecs autoscaling "
        f"resource_id={resource_id} min={args.min_capacity} max={args.max_capacity} "
        f"depth_up={args.depth_up_threshold} age_up={args.age_up_threshold} depth_down={args.depth_down_threshold}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
