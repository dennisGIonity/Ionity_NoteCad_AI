# Downloads the companion's models (about 3.4 GB) into .\models. Models are not committed.
param([string]$Dest = ".\models", [switch]$E4B)

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$files = @(
  @{ url = "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_K_M.gguf"; name = "gemma-4-E2B-it-Q4_K_M.gguf" },
  @{ url = "https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF/resolve/main/embeddinggemma-300M-Q8_0.gguf"; name = "embeddinggemma-300M-Q8_0.gguf" }
)
if ($E4B) {
  $files += @{ url = "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf"; name = "gemma-4-E4B-it-Q4_K_M.gguf" }
}
foreach ($f in $files) {
  $out = Join-Path $Dest $f.name
  if (Test-Path $out) { Write-Host "have $($f.name)"; continue }
  Write-Host "downloading $($f.name) ..."
  curl.exe -L --fail --retry 3 -o $out $f.url
}
Write-Host "models in $Dest"
