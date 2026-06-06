# velog-uploader

마크다운 파일 하나로 Velog 포스트를 자동 업로드하는 Python 스크립트입니다.

## 요구사항

- Python 3.10+
- Velog 계정

## 설치

```bash
git clone https://github.com/LSHgrandvoyage/velog-uploader.git
cd velog-uploader

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

## 환경 설정

`.env.example`을 복사해 `.env`를 만들고 토큰을 입력합니다.

```bash
cp .env.example .env
```

**토큰 발급 방법**

1. 브라우저에서 [velog.io](https://velog.io) 로그인
2. F12 → Application → Cookies → `https://velog.io`
3. `access_token`, `refresh_token` 값을 각각 복사해 `.env`에 붙여넣기

```
VELOG_ACCESS_TOKEN=여기에_access_token_붙여넣기
VELOG_REFRESH_TOKEN=여기에_refresh_token_붙여넣기
```

> **access_token이 만료되면 자동으로 갱신됩니다.** refresh_token까지 만료된 경우에만 위 과정을 다시 진행하면 됩니다.

## 사용법

### 1. 마크다운 파일 작성

파일 상단에 `---`로 감싼 frontmatter를 작성합니다.

```markdown
---
title: 포스트 제목
tags: [태그1, 태그2]
private: false
---

## 본문 시작

마크다운으로 자유롭게 작성하세요.
```

**frontmatter 옵션**

- `title` : 포스트 제목 (필수 입력)
- `tags` : 태그 목록 (Default = [])
- `private` : 비공개 여부 (Default = false)
- `temp` : 임시저장 여부 (Default = false)

### 2. 업로드

```bash
source .venv/bin/activate
python3 velog.py <내글>.md
```

업로드가 완료되면 터미널에 포스트 URL이 출력됩니다.

## 주의사항

- 동일한 제목으로 재업로드하면 새 글이 생성됩니다 (수정 아님).
