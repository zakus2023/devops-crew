resource "aws_lb" "app" {
  name               = "${var.project}-${var.env}-alb"
  internal           = false
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb_sg.id]
}

# Blue/green target groups and test listener only when NOT using ECS (EC2/CodeDeploy/ssh_script path).
resource "aws_lb_target_group" "blue" {
  count    = var.enable_ecs ? 0 : 1
  name     = "${var.project}-${var.env}-tg-blue"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = aws_vpc.this.id
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group" "green" {
  count    = var.enable_ecs ? 0 : 1
  name     = "${var.project}-${var.env}-tg-green"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = aws_vpc.this.id
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.cert.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = var.enable_ecs ? aws_lb_target_group.ecs[0].arn : aws_lb_target_group.blue[0].arn
  }
}

# Test listener (port 9001) for blue/green only when using EC2 path.
resource "aws_lb_listener" "test" {
  count             = var.enable_ecs ? 0 : 1
  load_balancer_arn = aws_lb.app.arn
  port              = 9001
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.green[0].arn
  }
}