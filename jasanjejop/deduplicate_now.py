"""
기존 저장된 글 중 유사 글 일회성 정리 스크립트
실행: py deduplicate_now.py
"""

from db import deduplicate_all, get_count

print(f"정리 전 총 글 수: {get_count()}개")
print("유사 글 탐지 및 삭제 중... (시간이 걸릴 수 있어요)")

deleted = deduplicate_all()

print(f"삭제된 글 수: {deleted}개")
print(f"정리 후 총 글 수: {get_count()}개")
