#!/bin/bash
# 서버 최초 1회 실행 스크립트 - 모든 환경 자동 설치

echo "=== [1/6] 패키지 업데이트 ==="
sudo apt update && sudo apt upgrade -y

echo "=== [2/6] Python 및 필수 도구 설치 ==="
sudo apt install -y python3-pip python3-venv git

echo "=== [3/6] GitHub에서 코드 받기 ==="
cd /home/$USER
git clone https://github.com/hidesyes/telegram-bots.git
cd telegram-bots

echo "=== [4/6] 자산제곱 봇 라이브러리 설치 ==="
cd jasanjejop
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps
deactivate
cd ..

echo "=== [5/6] 리라이팅 봇 라이브러리 설치 ==="
cd rewriter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..

echo "=== [6/6] 서비스 등록 (24시간 자동 실행 설정) ==="
# 서비스 파일을 시스템 폴더에 복사
sudo cp jasanjejop/jasanjejop-bot.service /etc/systemd/system/
sudo cp rewriter/rewriter-bot.service /etc/systemd/system/

# 경로를 현재 유저에 맞게 자동 수정
sudo sed -i "s|/home/ubuntu|/home/$USER|g" /etc/systemd/system/jasanjejop-bot.service
sudo sed -i "s|/home/ubuntu|/home/$USER|g" /etc/systemd/system/rewriter-bot.service
sudo sed -i "s|User=ubuntu|User=$USER|g" /etc/systemd/system/jasanjejop-bot.service
sudo sed -i "s|User=ubuntu|User=$USER|g" /etc/systemd/system/rewriter-bot.service

sudo systemctl daemon-reload
sudo systemctl enable jasanjejop-bot
sudo systemctl enable rewriter-bot

echo ""
echo "=========================================="
echo "✅ 설치 완료!"
echo ""
echo "이제 아래 2가지를 직접 해주세요:"
echo ""
echo "1) 자산제곱 봇 .env 파일 생성:"
echo "   nano /home/$USER/telegram-bots/jasanjejop/.env"
echo ""
echo "2) 리라이팅 봇 .env 파일 생성:"
echo "   nano /home/$USER/telegram-bots/rewriter/.env"
echo ""
echo ".env 작성 후 아래 명령어로 봇 시작:"
echo "   sudo systemctl start jasanjejop-bot"
echo "   sudo systemctl start rewriter-bot"
echo "=========================================="
