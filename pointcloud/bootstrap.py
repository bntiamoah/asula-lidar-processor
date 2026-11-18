import json

from pointcloud.services import BUCKET, DEAD_LETTER_QUEUE, QUEUE, queue, storage


def main() -> None:
    s3 = storage()
    s3.create_bucket(Bucket=BUCKET)
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    sqs = queue()
    dead = sqs.create_queue(QueueName=DEAD_LETTER_QUEUE)["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=dead, AttributeNames=["QueueArn"])
    sqs.create_queue(
        QueueName=QUEUE,
        Attributes={
            "VisibilityTimeout": "60",
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": arn["Attributes"]["QueueArn"], "maxReceiveCount": 3}
            ),
        },
    )


if __name__ == "__main__":
    main()
