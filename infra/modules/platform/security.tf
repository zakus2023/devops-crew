data "aws_caller_identity" "current" {}

resource "aws_cloudtrail" "trail" {
  count                         = var.enable_cloudtrail ? 1 : 0
  name                          = "${var.project}-${var.env}-trail"
  s3_bucket_name                = var.cloudtrail_bucket
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
}

resource "aws_guardduty_detector" "gd" {
  count  = var.enable_guardduty ? 1 : 0
  enable = true
}

resource "aws_securityhub_account" "sh" {
  count                    = var.enable_securityhub ? 1 : 0
  enable_default_standards = false
}

resource "aws_inspector2_enabler" "insp" {
  count          = var.enable_inspector2 ? 1 : 0
  account_ids    = [data.aws_caller_identity.current.account_id]
  resource_types = ["EC2", "ECR"]
}

resource "aws_iam_role" "config_role" {
  count = var.enable_config ? 1 : 0
  name  = "${var.project}-${var.env}-config-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "config" {
  count      = var.enable_config ? 1 : 0
  role       = aws_iam_role.config_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_s3_bucket" "config" {
  count         = var.enable_config ? 1 : 0
  bucket_prefix = "${var.project}-${var.env}-config-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "config" {
  count                   = var.enable_config ? 1 : 0
  bucket                  = aws_s3_bucket.config[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "config" {
  count  = var.enable_config ? 1 : 0
  bucket = aws_s3_bucket.config[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSConfigBucketPermissionsCheck"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = "arn:aws:s3:::${aws_s3_bucket.config[0].bucket}"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        Sid       = "AWSConfigBucketExistenceCheck"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:ListBucket"
        Resource  = "arn:aws:s3:::${aws_s3_bucket.config[0].bucket}"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        Sid       = "AWSConfigBucketDelivery"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "arn:aws:s3:::${aws_s3_bucket.config[0].bucket}/config/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"         = "bucket-owner-full-control"
            "AWS:SourceAccount"    = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

resource "aws_config_configuration_recorder" "rec" {
  count    = var.enable_config ? 1 : 0
  name     = "${var.project}-${var.env}-recorder"
  role_arn = aws_iam_role.config_role[0].arn
  recording_group {
    all_supported                 = true
    include_global_resource_types = true
  }
}

resource "aws_config_delivery_channel" "chan" {
  count          = var.enable_config ? 1 : 0
  name           = "${var.project}-${var.env}-channel"
  s3_bucket_name = aws_s3_bucket.config[0].bucket
  s3_key_prefix  = "config"
  depends_on     = [aws_config_configuration_recorder.rec[0], aws_s3_bucket_policy.config[0]]
}

resource "aws_config_configuration_recorder_status" "rec_status" {
  count      = var.enable_config ? 1 : 0
  name       = aws_config_configuration_recorder.rec[0].name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.chan[0]]
}