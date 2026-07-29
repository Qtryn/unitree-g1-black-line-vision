param(
    [string]$Owner = "Qtryn",
    [string]$Repo = "unitree-g1-black-line-vision",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Require-Command {
    param([string]$Name, [string]$InstallCommand)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Host "Khong tim thay '$Name'. Cai bang lenh:" -ForegroundColor Red
        Write-Host "  $InstallCommand" -ForegroundColor Yellow
        exit 1
    }
}

Require-Command "git" "winget install --id Git.Git -e"
Require-Command "gh" "winget install --id GitHub.cli -e"

Write-Host "Kiem tra tai khoan GitHub..." -ForegroundColor Cyan
$authOutput = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Chua dang nhap GitHub CLI. Chay: gh auth login" -ForegroundColor Yellow
    gh auth login
}

$currentLogin = gh api user --jq .login
if ($LASTEXITCODE -ne 0) {
    throw "Khong doc duoc tai khoan GitHub dang dang nhap."
}

if ($currentLogin -ne $Owner) {
    Write-Host "Tai khoan hien tai: $currentLogin" -ForegroundColor Red
    Write-Host "Can dang nhap tai khoan: $Owner" -ForegroundColor Yellow
    Write-Host "Chay lan luot:" -ForegroundColor Yellow
    Write-Host "  gh auth logout" -ForegroundColor White
    Write-Host "  gh auth login" -ForegroundColor White
    Write-Host "Sau do chay lai script nay." -ForegroundColor Yellow
    exit 1
}

Write-Host "Dang dung tai khoan: $currentLogin" -ForegroundColor Green

if (-not (Test-Path ".git")) {
    git init
    git branch -M main
}

# Git identity is local to this repository only.
if (-not (git config user.name)) {
    git config user.name $Owner
}
if (-not (git config user.email)) {
    git config user.email "190820673+Qtryn@users.noreply.github.com"
}

# Ensure generated/runtime files are not committed.
$requiredIgnoreRules = @(
    ".venv/",
    "__pycache__/",
    "*.pyc",
    "outputs/*",
    "!outputs/.gitkeep",
    "calibration/tuned_parameters.yaml",
    "calibration/tuned_parameters.jpg",
    "*.mp4",
    "*.avi"
)

if (-not (Test-Path ".gitignore")) {
    New-Item -ItemType File -Path ".gitignore" | Out-Null
}

$ignoreText = Get-Content ".gitignore" -Raw
foreach ($rule in $requiredIgnoreRules) {
    if ($ignoreText -notmatch [regex]::Escape($rule)) {
        Add-Content ".gitignore" $rule
    }
}

Write-Host "Kiem tra file se commit..." -ForegroundColor Cyan
git add .
git status --short

$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "Khong co thay doi moi de commit." -ForegroundColor Yellow
} else {
    git commit -m "Initial release: Unitree G1 black line vision V3.1"
}

$remoteUrl = "https://github.com/$Owner/$Repo.git"
$repoExists = $false
gh repo view "$Owner/$Repo" *> $null
if ($LASTEXITCODE -eq 0) {
    $repoExists = $true
}

if (-not $repoExists) {
    Write-Host "Tao repository $Owner/$Repo..." -ForegroundColor Cyan
    if ($Visibility -eq "private") {
        gh repo create "$Owner/$Repo" --private --source=. --remote=origin --push --description "Camera-based black tape line detection and control estimation for Unitree G1 using OpenCV."
    } else {
        gh repo create "$Owner/$Repo" --public --source=. --remote=origin --push --description "Camera-based black tape line detection and control estimation for Unitree G1 using OpenCV."
    }
} else {
    Write-Host "Repository da ton tai: $Owner/$Repo" -ForegroundColor Yellow

    $origin = git remote get-url origin 2>$null
    if ($LASTEXITCODE -eq 0) {
        git remote set-url origin $remoteUrl
    } else {
        git remote add origin $remoteUrl
    }

    git push -u origin main
}

Write-Host "" 
Write-Host "Da push thanh cong:" -ForegroundColor Green
Write-Host "https://github.com/$Owner/$Repo" -ForegroundColor Cyan
