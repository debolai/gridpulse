# One private repository per component image. Images are tagged by Git SHA and scanned on push;
# untagged layers expire after a day and only the 10 most recent tags are kept.

resource "aws_ecr_repository" "this" {
  for_each             = toset(var.components)
  name                 = "gridpulse/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # images are rebuilt from Git; nothing irreplaceable lives here

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 1 }
        action       = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the 10 most recent images"
        selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
        action       = { type = "expire" }
      },
    ]
  })
}
