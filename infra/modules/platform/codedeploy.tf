# CodeDeploy and artifacts bucket only when NOT using ECS (EC2 blue/green path).
resource "aws_s3_bucket" "artifacts" {
  count         = var.enable_ecs ? 0 : 1
  bucket_prefix = "${var.project}-${var.env}-codedeploy-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  count                   = var.enable_ecs ? 0 : 1
  bucket                  = aws_s3_bucket.artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "codedeploy_assume" {
  count = var.enable_ecs ? 0 : 1
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codedeploy_role" {
  count                = var.enable_ecs ? 0 : 1
  name                 = "${var.project}-${var.env}-codedeploy-role"
  assume_role_policy   = data.aws_iam_policy_document.codedeploy_assume[0].json
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.codedeploy_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
}

resource "aws_iam_policy" "codedeploy_autoscaling" {
  count  = var.enable_ecs ? 0 : 1
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
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.codedeploy_role[0].name
  policy_arn = aws_iam_policy.codedeploy_autoscaling[0].arn
}

resource "aws_iam_role_policy_attachment" "codedeploy_autoscaling_full" {
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.codedeploy_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/AutoScalingFullAccess"
}

resource "aws_codedeploy_app" "app" {
  count              = var.enable_ecs ? 0 : 1
  name               = "${var.project}-${var.env}-codedeploy-app"
  compute_platform   = "Server"
}

resource "aws_codedeploy_deployment_group" "dg" {
  count                  = var.enable_ecs ? 0 : 1
  app_name               = aws_codedeploy_app.app[0].name
  deployment_group_name  = "${var.project}-${var.env}-dg"
  service_role_arn       = aws_iam_role.codedeploy_role[0].arn
  autoscaling_groups     = [aws_autoscaling_group.blue[0].name, aws_autoscaling_group.green[0].name]
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
      name = aws_lb_target_group.blue[0].name
    }
    target_group_info {
      name = aws_lb_target_group.green[0].name
    }
  }
  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM", "DEPLOYMENT_STOP_ON_REQUEST"]
  }
  # Only alb_5xx is used to stop deployments. unhealthy_hosts is not included because it
  # fires during normal blue/green (e.g. draining or new instances not yet healthy), which
  # would stop the deployment prematurely.
  alarm_configuration {
    enabled                  = var.enable_deployment_alarms
    ignore_poll_alarm_failure = true
    alarms                   = var.enable_deployment_alarms ? [aws_cloudwatch_metric_alarm.alb_5xx.alarm_name] : []
  }
}