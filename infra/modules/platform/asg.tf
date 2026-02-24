data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

locals {
  ami = var.ami_id != "" ? var.ami_id : data.aws_ami.al2023.id
  user_data = <<-EOF
    #!/bin/bash
    set -e
    log() { echo "[$(date -u +%FT%TZ)] $*"; }
    retry() {
      local n=0
      local max=12
      local delay=10
      until "$@"; do
        n=$((n+1))
        if [ "$n" -ge "$max" ]; then
          return 1
        fi
        log "retry $n/$max: $*"
        sleep "$delay"
      done
    }
    echo "${var.env}" > /opt/bluegreen-env
    REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region || true)
    if [ -z "$REGION" ]; then
      REGION="${var.region}"
    fi
    PKG_MGR="yum"
    if command -v dnf >/dev/null 2>&1; then
      PKG_MGR="dnf"
    fi
    log "Refreshing package metadata"
    retry $PKG_MGR clean all
    retry $PKG_MGR makecache --setopt=skip_if_unavailable=true
    log "Installing base packages"
    retry $PKG_MGR update -y --setopt=skip_if_unavailable=true
    retry $PKG_MGR install -y docker ruby wget amazon-cloudwatch-agent --setopt=skip_if_unavailable=true
    systemctl enable docker
    systemctl start docker
    cd /home/ec2-user
    wget https://aws-codedeploy-$${REGION}.s3.$${REGION}.amazonaws.com/latest/install
    chmod +x ./install
    ./install auto
    systemctl start codedeploy-agent
    /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
      -a fetch-config -m ec2 \
      -c ssm:/${var.project}/${var.env}/cloudwatch/agent-config -s
  EOF
}

# Launch template and ASGs only when NOT using ECS (EC2/CodeDeploy/ssh_script path).
resource "aws_launch_template" "lt" {
  count         = var.enable_ecs ? 0 : 1
  name_prefix   = "${var.project}-${var.env}-lt-"
  image_id      = local.ami
  instance_type = var.instance_type
  key_name      = var.key_name != "" ? var.key_name : null
  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_profile[0].name
  }
  vpc_security_group_ids = [aws_security_group.ec2_sg[0].id]
  user_data              = base64encode(local.user_data)
  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.project}-${var.env}-app"
      Env  = var.env
    }
  }
}

resource "aws_autoscaling_group" "blue" {
  count                       = var.enable_ecs ? 0 : 1
  name                        = "${var.project}-${var.env}-asg-blue"
  min_size                    = var.min_size
  max_size                    = var.max_size
  desired_capacity            = var.desired_capacity
  vpc_zone_identifier         = aws_subnet.private[*].id
  target_group_arns          = [aws_lb_target_group.blue[0].arn]
  wait_for_capacity_timeout  = "0"
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 180
    }
  }
  launch_template {
    id      = aws_launch_template.lt[0].id
    version = "$Latest"
  }
  tag {
    key                 = "Name"
    value               = "${var.project}-${var.env}-blue"
    propagate_at_launch = true
  }
  tag {
    key                 = "Env"
    value               = var.env
    propagate_at_launch = true
  }
  lifecycle {
    ignore_changes = [desired_capacity]
  }
}

resource "aws_autoscaling_group" "green" {
  count                       = var.enable_ecs ? 0 : 1
  name                        = "${var.project}-${var.env}-asg-green"
  min_size                    = var.min_size
  max_size                    = var.max_size
  desired_capacity            = var.desired_capacity
  vpc_zone_identifier         = aws_subnet.private[*].id
  target_group_arns          = [aws_lb_target_group.green[0].arn]
  wait_for_capacity_timeout  = "0"
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 180
    }
  }
  launch_template {
    id      = aws_launch_template.lt[0].id
    version = "$Latest"
  }
  tag {
    key                 = "Name"
    value               = "${var.project}-${var.env}-green"
    propagate_at_launch = true
  }
  tag {
    key                 = "Env"
    value               = var.env
    propagate_at_launch = true
  }
  lifecycle {
    ignore_changes = [desired_capacity]
  }
}