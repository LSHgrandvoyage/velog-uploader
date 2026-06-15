import os
import re
import sys
import time
import email
import imaplib
from email.utils import parsedate_to_datetime

import yaml
import requests
from dotenv import load_dotenv, set_key

load_dotenv()

GRAPHQL_URL = "https://v3.velog.io/graphql"
AUTH_HOST = "https://api.velog.io"
IMAP_HOST = "imap.gmail.com"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# velog 로그인 메일에 담긴 링크: https://velog.io/email-login?code=<코드>
LOGIN_CODE_RE = re.compile(r"email-login\?code=([A-Za-z0-9_-]+)")

_tokens = {
    "access": os.getenv("VELOG_ACCESS_TOKEN", ""),
    "refresh": os.getenv("VELOG_REFRESH_TOKEN", ""),
}


def _restore_token() -> None:
    if not _tokens["refresh"]:
        raise RuntimeError(
            "VELOG_REFRESH_TOKEN이 없습니다. .env 파일에 refresh_token을 추가하세요.\n"
            "브라우저 F12 → Application → Cookies → velog.io → refresh_token"
        )

    query = """
    query RestoreToken {
      restoreToken {
        accessToken
        refreshToken
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query},
        cookies={"refresh_token": _tokens["refresh"]},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    result = data.get("data", {}).get("restoreToken") if "errors" not in data else None
    if not result or not result.get("accessToken"):
        raise RuntimeError("refresh_token이 만료됐습니다(유효기간 3일).")

    _tokens["access"] = result["accessToken"]
    _tokens["refresh"] = result["refreshToken"]

    set_key(ENV_FILE, "VELOG_ACCESS_TOKEN", _tokens["access"])
    set_key(ENV_FILE, "VELOG_REFRESH_TOKEN", _tokens["refresh"])
    print("토큰 갱신 완료")


def _gql(query: str, variables: dict, _retried: bool = False) -> dict:
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        cookies={"access_token": _tokens["access"]},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        is_auth_error = any(
            "auth" in str(e).lower() or "forbidden" in str(e).lower() or "unauthorized" in str(e).lower()
            for e in data["errors"]
        )
        if is_auth_error and not _retried:
            print("access_token 만료 — 자동 갱신 중...")
            _restore_token()
            return _gql(query, variables, _retried=True)
        raise RuntimeError(data["errors"])

    return data["data"]


def _current_username() -> str | None:
    """현재 access_token으로 로그인된 username을 반환한다.

    velog는 access_token이 만료/무효일 때 errors 없이 currentUser=null을
    돌려주므로, 인증 실패는 None으로 나타난다.
    """
    query = """
    query CurrentUser {
      currentUser {
        username
      }
    }
    """
    result = _gql(query, {})
    user = result["currentUser"]
    return user["username"] if user else None


def _ensure_auth() -> str:
    """업로드 전에 인증을 보장하고 로그인된 username을 반환한다.

    1) access_token이 살아있으면 그대로 사용
    2) 만료됐으면 refresh_token으로 갱신
    3) 그것도 만료됐으면 이메일 매직링크 로그인으로 토큰을 새로 발급 (무인)
    """
    username = _current_username()
    if username:
        return username

    if _tokens["refresh"]:
        print("access_token 만료 — refresh_token으로 갱신 중...")
        try:
            _restore_token()
            username = _current_username()
            if username:
                return username
        except Exception as e:
            print(f"refresh_token 갱신 실패: {e}")

    print("토큰이 모두 만료됨 — 이메일 로그인으로 재발급합니다...")
    _email_login()
    username = _current_username()
    if not username:
        raise RuntimeError("이메일 로그인 후에도 인증에 실패했습니다.")
    return username


def _email_login() -> None:
    """velog 이메일 매직링크 로그인을 자동 수행해 토큰을 발급받는다.

    sendmail 요청 → Gmail(IMAP) 폴링으로 코드 추출 → code 교환 → .env 저장.
    """
    velog_email = os.getenv("VELOG_EMAIL", "")
    app_pw = os.getenv("GMAIL_APP_PASSWORD", "")
    if not velog_email or not app_pw:
        raise RuntimeError(
            "이메일 자동 로그인 설정이 없습니다. .env에 VELOG_EMAIL과 "
            "GMAIL_APP_PASSWORD를 추가하세요.\n"
            "앱 비밀번호: 구글 계정 → 보안 → 2단계 인증 → 앱 비밀번호"
        )

    sent_at = time.time()
    _send_login_mail(velog_email)
    code = _wait_for_login_code(velog_email, app_pw, since=sent_at)
    _exchange_code(code)


def _send_login_mail(email_addr: str) -> None:
    resp = requests.post(
        f"{AUTH_HOST}/api/v2/auth/sendmail",
        json={"email": email_addr},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("registered", False):
        raise RuntimeError(
            f"'{email_addr}'로 가입된 velog 계정이 없습니다. VELOG_EMAIL을 확인하세요."
        )
    print(f"{email_addr}로 로그인 메일 발송 — 도착 대기 중...")


def _wait_for_login_code(
    imap_user: str, imap_pw: str, since: float, timeout: int = 90, interval: int = 5
) -> str:
    """verify@velog.io가 보낸 최신 로그인 메일에서 코드를 추출한다."""
    deadline = time.time() + timeout
    with imaplib.IMAP4_SSL(IMAP_HOST) as M:
        M.login(imap_user, imap_pw)
        while time.time() < deadline:
            # 스팸/프로모션함으로 분류될 수 있어 전체 메일함까지 검색
            for mailbox in ('"[Gmail]/All Mail"', "INBOX"):
                try:
                    typ, _ = M.select(mailbox)
                    if typ != "OK":
                        continue
                except imaplib.IMAP4.error:
                    continue

                typ, data = M.search(None, "FROM", "verify@velog.io", "UNSEEN")
                if typ != "OK" or not data or not data[0]:
                    continue

                for mid in reversed(data[0].split()):
                    typ, msg_data = M.fetch(mid, "(RFC822)")
                    if typ != "OK":
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])

                    # sendmail 호출 이전에 온 옛 메일은 무시 (재사용 방지)
                    try:
                        msg_ts = parsedate_to_datetime(msg["Date"]).timestamp()
                        if msg_ts < since - 120:
                            continue
                    except (TypeError, ValueError):
                        pass

                    code = _extract_code(msg)
                    if code:
                        M.store(mid, "+FLAGS", "\\Seen")
                        return code
            time.sleep(interval)

    raise RuntimeError(
        "로그인 메일을 시간 내에 받지 못했습니다. 스팸함과 VELOG_EMAIL을 확인하세요."
    )


def _extract_code(msg: email.message.Message) -> str | None:
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "ignore")
        m = LOGIN_CODE_RE.search(text)
        if m:
            return m.group(1)
    return None


def _exchange_code(code: str) -> None:
    resp = requests.get(
        f"{AUTH_HOST}/api/v2/auth/code/{code}",
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    if resp.status_code == 404:
        raise RuntimeError("로그인 코드가 유효하지 않습니다.")
    resp.raise_for_status()
    data = resp.json()

    tokens = data.get("tokens")
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError(f"토큰 발급 실패: {str(data)[:200]}")

    _tokens["access"] = tokens["access_token"]
    _tokens["refresh"] = tokens["refresh_token"]
    set_key(ENV_FILE, "VELOG_ACCESS_TOKEN", _tokens["access"])
    set_key(ENV_FILE, "VELOG_REFRESH_TOKEN", _tokens["refresh"])
    print("이메일 로그인 완료 — 토큰 재발급 및 저장 완료")


def _get_series_id(series_name: str, username: str) -> str:
    query = """
    query SeriesList($input: GetSeriesListInput!) {
      seriesList(input: $input) {
        id
        name
      }
    }
    """
    result = _gql(query, {"input": {"username": username}})
    for series in result["seriesList"]:
        if series["name"] == series_name:
            return series["id"]

    raise ValueError(
        f"시리즈 '{series_name}'를 찾을 수 없습니다. "
        "velog.io에서 해당 시리즈를 먼저 만들어주세요 (API로는 시리즈 생성이 불가능합니다)."
    )


def _make_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug


def parse_md(filepath: str) -> tuple[dict, str]:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        raise ValueError("frontmatter가 없습니다. 파일 상단에 ---로 시작하는 메타정보를 추가하세요.")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter 형식이 올바르지 않습니다. ---로 열고 닫아야 합니다.")

    meta = yaml.safe_load(parts[1])
    body = parts[2].strip()
    return meta, body


def upload_post(
    title: str,
    body: str,
    tags: list[str] = [],
    is_private: bool = False,
    is_temp: bool = False,
    series: str | None = None,
    description: str | None = None,
) -> dict:
    mutation = """
    mutation WritePost($input: WritePostInput!) {
      writePost(input: $input) {
        id
        title
        url_slug
        user { username }
      }
    }
    """
    username = _ensure_auth()
    series_id = _get_series_id(series, username) if series else None

    variables = {
        "input": {
            "title": title,
            "body": body,
            "tags": tags,
            "is_markdown": True,
            "is_temp": is_temp,
            "is_private": is_private,
            "url_slug": _make_slug(title),
            "thumbnail": None,
            "meta": {"short_description": description} if description else {},
            "series_id": series_id,
        }
    }
    result = _gql(mutation, variables)
    post = result["writePost"]
    username = post["user"]["username"]
    url = f"https://velog.io/@{username}/{post['url_slug']}"
    print(f"업로드 완료: {url}")
    return post


def main():
    if len(sys.argv) < 2:
        print("사용법: python3 velog.py <파일명.md>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"파일을 찾을 수 없습니다: {filepath}")
        sys.exit(1)

    meta, body = parse_md(filepath)

    title = meta.get("title")
    if not title:
        raise ValueError("frontmatter에 title이 없습니다.")

    upload_post(
        title=title,
        body=body,
        tags=meta.get("tags", []),
        is_private=meta.get("private", False),
        is_temp=meta.get("temp", False),
        series=meta.get("series"),
        description=meta.get("description"),
    )


if __name__ == "__main__":
    main()
