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

**1. 토큰 발급 (최초 1회)**

1. 브라우저에서 [velog.io](https://velog.io) 로그인
2. F12 → Application → Cookies → `https://velog.io`
3. `access_token`, `refresh_token` 값을 각각 복사해 `.env`에 붙여넣기

```
VELOG_ACCESS_TOKEN=여기에_access_token_붙여넣기
VELOG_REFRESH_TOKEN=여기에_refresh_token_붙여넣기
```

**2. 이메일 자동 로그인 설정 (토큰 무한 자동 갱신)**

velog의 access_token은 24시간, refresh_token은 3일 만에 만료됩니다. 두 토큰이 모두
만료되면 스크립트가 **velog 로그인 메일을 자동으로 받아 새 토큰을 발급**하므로, 한 번
설정해두면 더 이상 브라우저에서 토큰을 복사할 필요가 없습니다.

1. 구글 계정에서 **2단계 인증**을 켭니다.
2. [앱 비밀번호](https://myaccount.google.com/apppasswords)를 발급합니다 (16자리).
3. `.env`에 velog 로그인 이메일과 앱 비밀번호를 추가합니다.

```
VELOG_EMAIL=velog_로그인용_이메일주소
GMAIL_APP_PASSWORD=구글_앱_비밀번호_16자리
```

> 이메일은 코드 추출을 위해 **IMAP으로 읽기만** 하며, 앱 비밀번호는 `.env`에만 저장됩니다.
> velog 로그인 이메일이 Gmail이어야 합니다.

**동작 방식**

업로드할 때마다 ① access_token 사용 → ② 만료 시 refresh_token으로 갱신 →
③ 둘 다 만료 시 이메일 로그인으로 재발급, 순서로 인증을 자동 처리합니다.
3일에 한 번이라도 업로드하면 갱신 체인이 유지되고, 그보다 오래 쉬어도
이메일 로그인이 무인으로 복구합니다.

## 사용법

### 1. 마크다운 파일 작성

파일 상단에 `---`로 감싼 frontmatter를 작성합니다.

```markdown
---
title: 포스트 제목
tags: [태그1, 태그2]
private: false
series: 시리즈 이름
description: 포스트 목록에서 보일 짧은 소개 문구
---

## 본문 시작

마크다운으로 자유롭게 작성하세요.
```

**frontmatter 옵션**

- `title` : 포스트 제목 (필수 입력)
- `tags` : 태그 목록 (Default = [])
- `private` : 비공개 여부 (Default = false)
- `temp` : 임시저장 여부 (Default = false)
- `series` : 시리즈 이름 (Default = 없음). velog.io에 동일한 이름의 시리즈가 미리 존재해야 합니다 (API로 시리즈 생성은 불가능).
- `description` : 포스트 목록/공유 시 보이는 짧은 소개 문구 (Default = 없음, 미입력 시 velog가 자동 생성).

### 2. 업로드

```bash
source .venv/bin/activate
python3 velog.py <내글>.md
```

업로드가 완료되면 터미널에 포스트 URL이 출력됩니다.

## 주의사항

- 동일한 제목으로 재업로드하면 새 글이 생성됩니다 (수정 아님).
