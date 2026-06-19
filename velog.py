import os
import re
import sys
import mimetypes
import yaml
import requests
from dotenv import load_dotenv, set_key

load_dotenv()

GRAPHQL_URL = "https://v3.velog.io/graphql"
UPLOAD_URL = "https://v2.velog.io/api/v2/files/upload"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 썸네일 이미지가 보관된 디렉토리. 파일명은 "<시리즈명>_thumbnail.<확장자>" 형태.
THUMBNAIL_DIR = os.getenv("THUMBNAIL_DIR", "")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

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

    if "errors" in data:
        raise RuntimeError(
            "refresh_token도 만료됐습니다. 브라우저에서 다시 로그인 후 두 토큰 모두 재복사하세요."
        )

    result = data["data"]["restoreToken"]
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


def _get_username() -> str:
    query = """
    query CurrentUser {
      currentUser {
        username
      }
    }
    """
    result = _gql(query, {})
    user = result["currentUser"]
    if not user:
        raise RuntimeError("로그인 정보를 확인할 수 없습니다. 토큰을 확인하세요.")
    return user["username"]


def _get_series_id(series_name: str) -> str:
    username = _get_username()
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


def _find_thumbnail(series: str | None) -> str | None:
    """시리즈명으로 THUMBNAIL_DIR에서 '<series>_thumbnail.<ext>' 파일을 찾는다.

    확장자는 자동 탐색하고, 파일명 대소문자는 무시한다. 없으면 None.
    """
    if not series or not THUMBNAIL_DIR:
        return None
    if not os.path.isdir(THUMBNAIL_DIR):
        print(f"경고: THUMBNAIL_DIR 경로를 찾을 수 없습니다: {THUMBNAIL_DIR}")
        return None

    target = f"{series}_thumbnail".lower()
    for name in os.listdir(THUMBNAIL_DIR):
        stem, ext = os.path.splitext(name)
        if stem.lower() == target and ext.lower() in IMAGE_EXTS:
            return os.path.join(THUMBNAIL_DIR, name)
    return None


def upload_image(filepath: str, ref_id: str, _retried: bool = False) -> str:
    """이미지를 velog에 업로드하고 CDN URL을 반환한다.

    ref_id는 이미지가 속한 글의 id여야 한다(소유권 검증). 따라서 글을 먼저
    생성한 뒤 그 id로 호출해야 한다.
    """
    ctype = mimetypes.guess_type(filepath)[0] or "image/jpeg"
    with open(filepath, "rb") as f:
        image_bytes = f.read()

    resp = requests.post(
        UPLOAD_URL,
        files={"image": (os.path.basename(filepath), image_bytes, ctype)},
        data={"type": "post", "ref_id": ref_id},
        cookies={"access_token": _tokens["access"]},
        headers={"origin": "https://velog.io", "referer": "https://velog.io/"},
        timeout=30,
    )

    if resp.status_code in (401, 403) and not _retried:
        print("이미지 업로드 인증 만료 — 토큰 갱신 중...")
        _restore_token()
        return upload_image(filepath, ref_id, _retried=True)

    resp.raise_for_status()
    return resp.json()["path"]


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
) -> dict:
    write_mutation = """
    mutation WritePost($input: WritePostInput!) {
      writePost(input: $input) {
        id
        title
        url_slug
        user { username }
      }
    }
    """
    edit_mutation = """
    mutation EditPost($input: EditPostInput!) {
      editPost(input: $input) {
        id
      }
    }
    """
    series_id = _get_series_id(series) if series else None

    base_input = {
        "title": title,
        "body": body,
        "tags": tags,
        "is_markdown": True,
        "is_temp": is_temp,
        "is_private": is_private,
        "url_slug": _make_slug(title),
        "thumbnail": None,
        "meta": {},
        "series_id": series_id,
    }
    # 1) 글 생성 (썸네일 없이) → id 확보
    post = _gql(write_mutation, {"input": base_input})["writePost"]

    # 2~3) 썸네일이 있으면 그 글 id로 이미지 업로드 후 editPost로 주입
    thumb_path = _find_thumbnail(series)
    if thumb_path:
        thumbnail_url = upload_image(thumb_path, post["id"])
        edit_input = {**base_input, "id": post["id"], "thumbnail": thumbnail_url}
        _gql(edit_mutation, {"input": edit_input})
        print(f"썸네일 적용: {os.path.basename(thumb_path)}")
    elif series:
        print(f"썸네일 없음: '{series}_thumbnail.*' 파일을 찾지 못했습니다.")

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
    )


if __name__ == "__main__":
    main()
