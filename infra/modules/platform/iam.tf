# EC2 instance role and profile only when NOT using ECS (used by ASG launch template).
data "aws_iam_policy_document" "ec2_assume" {
  count = var.enable_ecs ? 0 : 1
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2_role" {
  count                = var.enable_ecs ? 0 : 1
  name                 = "${var.project}-${var.env}-ec2-role"
  assume_role_policy   = data.aws_iam_policy_document.ec2_assume[0].json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr" {
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "cw_agent" {
  count      = var.enable_ecs ? 0 : 1
  role       = aws_iam_role.ec2_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  count = var.enable_ecs ? 0 : 1
  name  = "${var.project}-${var.env}-ec2-profile"
  role  = aws_iam_role.ec2_role[0].name
}