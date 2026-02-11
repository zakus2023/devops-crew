locals {
  cw_agent_config = jsonencode({
    logs = {
      logs_collected = {
        files = {
          collect_list = [
            {
              file_path       = "/var/lib/docker/containers/*/*.log"
              log_group_name  = "/${var.project}/${var.env}/docker"
              log_stream_name = "{instance_id}"
              timezone        = "UTC"
            },
            {
              file_path       = "/var/log/messages"
              log_group_name  = "/${var.project}/${var.env}/system"
              log_stream_name = "{instance_id}"
              timezone        = "UTC"
            }
          ]
        }
      }
    }
    metrics = {
      metrics_collected = {
        cpu = {
          measurement                 = ["cpu_usage_idle", "cpu_usage_user", "cpu_usage_system"]
          metrics_collection_interval = 60
          totalcpu                   = true
        }
        disk = {
          measurement                 = ["used_percent"]
          metrics_collection_interval = 60
          resources                   = ["*"]
        }
        mem = {
          measurement                 = ["mem_used_percent"]
          metrics_collection_interval = 60
        }
      }
      append_dimensions = {
        InstanceId           = "$${aws:InstanceId}"
        AutoScalingGroupName = "$${aws:AutoScalingGroupName}"
      }
    }
  })
}

resource "aws_cloudwatch_log_group" "docker" {
  name              = "/${var.project}/${var.env}/docker"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "system" {
  name              = "/${var.project}/${var.env}/system"
  retention_in_days = 14
}

resource "aws_ssm_parameter" "cw_agent_config" {
  name      = "/${var.project}/${var.env}/cloudwatch/agent-config"
  type      = "String"
  value     = local.cw_agent_config
  overwrite = true
}