resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${var.project}-${var.env}-codedeploy-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "codedeploy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codedeploy_role" {
  name               = "${var.project}-${var.env}-codedeploy-role"
  assume_role_policy = data.aws_iam_policy_document.codedeploy_assume.json
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
}

resource "aws_iam_policy" "codedeploy_autoscaling" {
  name   = "${var.project}-${var.env}-codedeploy-autoscaling"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "autoscaling:*",
          "ec2:Describe*",
          "elasticloadbalancing:*",
          "iam:PassRole",
          "iam:GetRole",
          "iam:CreateServiceLinkedRole",
          "iam:ListRoles",
          "iam:ListInstanceProfiles"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "codedeploy_autoscaling" {
  role       = aws_iam_role.codedeploy_role.name
  policy_arn = aws_iam_policy.codedeploy_autoscaling.arn
}

resource "aws_iam_role_policy_attachment" "codedeploy_autoscaling_full" {
  role       = aws_iam_role.codedeploy_role.name
  policy_arn = "arn:aws:iam::aws:policy/AutoScalingFullAccess"
}


resource "aws_codedeploy_app" "app" {
  name             = "${var.project}-${var.env}-codedeploy-app"
  compute_platform = "Server"
}

resource "aws_codedeploy_deployment_group" "dg" {
  app_name              = aws_codedeploy_app.app.name
  deployment_group_name = "${var.project}-${var.env}-dg"
  service_role_arn      = aws_iam_role.codedeploy_role.arn
  # DISCOVER_EXISTING: use pre-created blue + green ASGs (no CreateAutoScalingGroup by CodeDeploy).
  # Use COPY_AUTO_SCALING_GROUP only if CodeDeploy role can create ASGs and you want dynamic green fleet.
  autoscaling_groups    = [aws_autoscaling_group.blue.name, aws_autoscaling_group.green.name]
  deployment_style {
    deployment_type   = "BLUE_GREEN"
    deployment_option = "WITH_TRAFFIC_CONTROL"
  }
  blue_green_deployment_config {
    deployment_ready_option {
      action_on_timeout    = "STOP_DEPLOYMENT"
      wait_time_in_minutes = 10
    }
    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = 5
    }
    green_fleet_provisioning_option {
      action = "DISCOVER_EXISTING"
    }
  }
  load_balancer_info {
    target_group_info {
      name = aws_lb_target_group.blue.name
    }
    target_group_info {
      name = aws_lb_target_group.green.name
    }
  }
  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM", "DEPLOYMENT_STOP_ON_REQUEST"]
  }
  alarm_configuration {
    enabled                  = var.enable_deployment_alarms
    ignore_poll_alarm_failure = true
    alarms                   = var.enable_deployment_alarms ? [
      aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.unhealthy_hosts.alarm_name,
    ] : []
  }
}