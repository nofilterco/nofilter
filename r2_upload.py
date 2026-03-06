import os
import boto3
from dotenv import load_dotenv

def upload_file(local_path: str, key: str) -> str:
    load_dotenv()
    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET")
    public_base = os.getenv("R2_PUBLIC_BASE_URL").rstrip("/")

    if not all([account_id, access_key, secret_key, bucket, public_base]):
        raise RuntimeError("Missing R2 env vars. Check .env")

    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    s3.upload_file(
        local_path,
        bucket,
        key,
        ExtraArgs={
            "ContentType": "image/png",
            # If you’re using a truly public bucket/domain this is enough.
        },
    )

    return f"{public_base}/{key}"