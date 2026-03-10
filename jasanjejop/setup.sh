#!/bin/bash
# 자산제곱 분석 봇 - 서버 자동 셋업 스크립트

echo "=== 패키지 업데이트 ==="
sudo apt update && sudo apt upgrade -y

echo "=== Python 및 기본 도구 설치 ==="
sudo apt install -y python3-pip python3-venv

echo "=== 가상환경 생성 (라이브러리를 독립적으로 관리하는 공간) ==="
python3 -m venv venv
source venv/bin/activate

echo "=== 라이브러리 설치 ==="
pip install -r requirements.txt

echo "=== Playwright 브라우저 설치 (스크래핑용) ==="
playwright install chromium
playwright install-deps

echo ""
echo "✅ 셋업 완료!"
echo "다음 단계: .env 파일 생성 후 'sudo systemctl start jasanjejop-bot' 실행"
