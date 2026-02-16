# Bastion only when NOT using ECS (needed for DEPLOY_METHOD=ssh_script to reach EC2).
# Set enable_bastion = true and key_name in tfvars; set BASTION_HOST to terraform output bastion_public_ip in .env.

resource "aws_security_group" "bastion_sg" {
  count       = var.enable_bastion && !var.enable_ecs ? 1 : 0
  name        = "${var.project}-${var.env}-bastion-sg"
  description = "Bastion: SSH from allowed CIDR"
  vpc_id      = aws_vpc.this.id
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_bastion_cidr]
    description = "SSH from user/office"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.project}-${var.env}-bastion-sg" }
}

resource "aws_instance" "bastion" {
  count         = var.enable_bastion && !var.enable_ecs && var.key_name != "" ? 1 : 0
  ami           = local.ami
  instance_type = "t3.micro"
  subnet_id     = aws_subnet.public[0].id
  key_name      = var.key_name
  vpc_security_group_ids = [aws_security_group.bastion_sg[0].id]
  tags = {
    Name = "${var.project}-${var.env}-bastion"
    Env  = var.env
  }
}
