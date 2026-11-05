# Image and test targets for local builds and CI alike. `docker buildx bake
# --load` builds and loads the images; `docker buildx bake test` runs the test
# targets in parallel. Version pins are at the top of the Dockerfile, so its
# targets also build without this file.

# CI sets LAYER_CACHE=gha to keep each image's layers in the GitHub Actions
# cache under the image's name. Local builds use the builder's own cache.
variable "LAYER_CACHE" {
  default = ""
}

function "cache_from" {
  params = [scopes]
  result = LAYER_CACHE == "gha" ? [for scope in scopes : "type=gha,scope=${scope}"] : []
}

function "cache_to" {
  params = [scope]
  result = LAYER_CACHE == "gha" ? ["type=gha,mode=max,scope=${scope}"] : []
}

group "default" {
  targets = ["arduino-workspace", "arduino-grader"]
}

group "test" {
  targets = ["arduino-frontend-test", "arduino-backend-test", "arduino-grader-test"]
}

# PrairieLearn runs linux/amd64 images.
target "arduino-workspace" {
  target     = "workspace"
  platforms  = ["linux/amd64"]
  tags       = ["pl-arduino-workspace:dev"]
  cache-from = cache_from(["arduino-workspace"])
  cache-to   = cache_to("arduino-workspace")
}

# The grader shares the toolchain stage with the workspace.
target "arduino-grader" {
  target     = "grader"
  platforms  = ["linux/amd64"]
  tags       = ["pl-arduino-grader:dev"]
  cache-from = cache_from(["arduino-grader", "arduino-workspace"])
  cache-to   = cache_to("arduino-grader")
}

# A test target passes when it builds; it produces no image.
target "_test" {
  output     = ["type=cacheonly"]
  cache-from = cache_from(["arduino-workspace", "arduino-grader"])
}

target "arduino-frontend-test" {
  inherits = ["_test"]
  target   = "frontend-test"
}

target "arduino-backend-test" {
  inherits = ["_test"]
  target   = "backend-test"
}

target "arduino-grader-test" {
  inherits = ["_test"]
  target   = "grader-test"
}
