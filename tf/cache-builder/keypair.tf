resource "tls_private_key" "cache_builder" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "cache_builder" {
  key_name   = join("-", [var.org_name, var.project_name, var.env, "cache-builder"])
  public_key = tls_private_key.cache_builder.public_key_openssh
  tags       = var.project_tags
}

# Write the private key to a local file so you can use it with ssh.
# The file is created at apply time and must not be committed to git.
resource "local_sensitive_file" "cache_builder_pem" {
  content         = tls_private_key.cache_builder.private_key_pem
  filename        = "${path.module}/cache-builder.pem"
  file_permission = "0600"
}

output "cache_builder_pem_path" {
  description = "Path to the private key file for SSH access"
  value       = local_sensitive_file.cache_builder_pem.filename
}
