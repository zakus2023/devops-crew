# Fill bucket, key, dynamodb_table after bootstrap apply
bucket         = "bluegreen-tfstate-20260226231329663200000002"
key            = "dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "bluegreen-tflock"
encrypt        = true
