# Optional ECS (Fargate) stack for DEPLOY_METHOD=ecs. When enable_ecs=true, traffic is routed to ECS instead of EC2 blue/green.

resource "aws_ecs_cluster" "app" {
  count = var.enable_ecs ? 1 : 0
  name  = "${var.project}-${var.env}-cluster"
  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# Execution role: pull image, write logs
resource "aws_iam_role" "ecs_execution" {
  count = var.enable_ecs ? 1 : 0
  name  = "${var.project}-${var.env}-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  count      = var.enable_ecs ? 1 : 0
  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Security group for ECS tasks: allow 8080 from ALB only
resource "aws_security_group" "ecs_tasks" {
  count       = var.enable_ecs ? 1 : 0
  name        = "${var.project}-${var.env}-ecs-tasks"
  description = "ECS tasks for app; allow 8080 from ALB"
  vpc_id      = aws_vpc.this.id
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.project}-${var.env}-ecs-tasks" }
}

# Target group for ECS tasks (ALB forwards to this)
resource "aws_lb_target_group" "ecs" {
  count       = var.enable_ecs ? 1 : 0
  name        = "${var.project}-${var.env}-ecs-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.this.id
  target_type = "ip"
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Listener rule: when ECS enabled, forward HTTPS traffic to ECS target group (priority 1)
resource "aws_lb_listener_rule" "ecs" {
  count        = var.enable_ecs ? 1 : 0
  listener_arn = aws_lb_listener.https.arn
  priority     = 1
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs[0].arn
  }
  condition {
    path_pattern {
      values = ["/*"]
    }
  }
}

# Task definition: Fargate, single container (image updated by pipeline via run_ecs_deploy)
resource "aws_ecs_task_definition" "app" {
  count                    = var.enable_ecs ? 1 : 0
  family                   = "${var.project}-${var.env}-app"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution[0].arn
  container_definitions = jsonencode([{
    name  = "app"
    image = "${aws_ecr_repository.app.repository_url}:unset"
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${var.project}-${var.env}-app"
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

# CloudWatch log group for ECS tasks
resource "aws_cloudwatch_log_group" "ecs_app" {
  count             = var.enable_ecs ? 1 : 0
  name              = "/ecs/${var.project}-${var.env}-app"
  retention_in_days  = 7
}

# ECS service: Fargate, desired 1, attached to ECS target group
resource "aws_ecs_service" "app" {
  count           = var.enable_ecs ? 1 : 0
  name            = "${var.project}-${var.env}-service"
  cluster         = aws_ecs_cluster.app[0].id
  task_definition = aws_ecs_task_definition.app[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks[0].id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.ecs[0].arn
    container_name   = "app"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener_rule.ecs]
}
