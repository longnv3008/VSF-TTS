# Prompt Tai Su Dung yt-dlp De Crawl Video Tu URL Hoac Tu Kenh

Tai lieu nay la prompt mau de ban tai su dung phan `yt-dlp` trong repo hien tai cho hai bai toan:

- Crawl video tu danh sach URL cu the
- Crawl video tu mot kenh YouTube, sau do lay danh sach URL video va dua vao pipeline xu ly

Prompt duoi day duoc viet theo dung tinh than cua codebase hien tai: uu tien service layer ro rang, co retry, cookie fallback, proxy failover, output runtime tach rieng, va de mo rong thanh workflow.

## Prompt Mau

```text
Toi muon ban giup toi tai su dung phan `yt-dlp` cua mot du an FastAPI hien co de xay dung mot module crawl YouTube co the hoat dong theo 2 che do:

1. Crawl tu danh sach video URL
2. Crawl tu mot channel URL, playlist URL, hoac tab video cua channel, sau do trich danh sach video URL roi crawl tung video

Hay thiet ke va scaffold cho toi theo cac yeu cau sau:

## 1. Muc tieu

Tao mot module Python/FastAPI de:

- Nhan input la `list[str]` URL video hoac `channel_url`
- Dung `yt-dlp` de lay metadata, tai audio/video neu can, va tai subtitle neu co
- Chuan hoa output thanh danh sach row noi bo de cac step sau co the dung lai
- Ho tro retry, backoff, cookie fallback, proxy failover
- Co kha nang mo rong thanh workflow processing sau crawl

## 2. Bat buoc giu giong kien truc hien tai

Hay giu cac nguyen tac kien truc sau:

- Logic `yt-dlp` phai nam trong service layer, khong nhet trong route
- Backend chia module theo `api`, `application`, `domain`
- Co `core/config.py` de doc env
- Co logging ro rang theo tung step
- Runtime data phai ghi ra `data/` va log ra `logs/`
- Co the dung lai cho dashboard/job system ve sau

## 3. Cach to chuc module mong muon

Hay de xuat mot module ten la `{MODULE_NAME}`, voi cau truc:

{MODULE_NAME}/
- api/
- application/
- domain/

Trong do:

- `api/` chua route va schema
- `application/` chua service crawl, discovery tu channel, worker, workflow
- `domain/` chua model input/output va state

## 4. Yeu cau chi tiet cho luong crawl tu URL

Hay tao mot service co ham tuong tu:

- `crawl_videos(urls: list[str], job_id: int | None = None, batch_name: str | None = None) -> list[dict[str, str]]`

Yeu cau:

- Dung `yt-dlp` voi option ro rang, de doc, de sua
- Co `logger` custom va `progress_hooks`
- Co ho tro `cookiefile`
- Co proxy failover nhu sau:
  - Uu tien `direct`
  - Chi chuyen sang proxy backup khi route hien tai bi rate limit/block
  - Khi route bi block thi dua vao cooldown
- Co cookie fallback:
  - Thu cookie chinh
  - Neu invalid thi thu cookie backup
  - Neu van loi thi fallback guest neu hop ly
- Co retry theo loai loi:
  - Rate limit/block
  - Loi mang thoang qua
  - Cookie invalid
  - Auth hard fail
- Tra ra row chuan hoa gom it nhat:
  - `video_id`
  - `title`
  - `source_url`
  - `duration_sec`
  - `raw_audio_path`
  - `subtitle_path`
  - `channel`
  - `uploader`
  - `upload_date`

## 5. Yeu cau chi tiet cho luong crawl tu channel

Hay tach luong channel thanh 2 phan ro rang:

### A. Discovery tu channel

Tao service vi du:

- `discover_video_urls_from_channel(channel_url: str, limit: int | None = None, newest_first: bool = True) -> list[str]`

Yeu cau:

- Dung `yt-dlp` o che do metadata/discovery, khong download audio ngay
- Ho tro channel URL, playlist URL, tab `/videos`
- Co the gioi han so video
- Co the bo qua video da xu ly neu truyen vao `existing_ids`
- Co log ro rang so video tim thay
- Co output metadata toi thieu cho discovery:
  - `video_id`
  - `webpage_url`
  - `title`
  - `channel`
  - `uploader`
  - `upload_date`

### B. Download theo danh sach URL da discover

Sau khi discovery xong, dua danh sach URL vao cung service crawl chinh thay vi viet lai logic download.

Muc tieu:

- Khong duplicate logic retry/proxy/cookie
- Discovery va download la 2 buoc rieng de de test va de resume

## 6. Workflow de xuat

Hay de xuat workflow co the mo rong nhu sau:

- `validate_input`
- `discover_channel_urls` neu input la channel
- `dedupe_urls`
- `crawl_media`
- `normalize_outputs`
- `export_metadata`

Neu input la list URL thi bo qua step `discover_channel_urls`.

## 7. Config/env mong muon

Hay de xuat env vars nhu sau:

- `YT_DLP_COOKIE_FILE`
- `YT_DLP_COOKIE_BACKUP_FILE`
- `YT_DLP_PROXY_BACKUPS`
- `CRAWL_MIN_DELAY_SEC`
- `CRAWL_MAX_DELAY_SEC`
- `CRAWL_JOB_COOLDOWN_SEC`
- `CRAWL_BLOCK_COOLDOWN_SEC`
- `CRAWL_URL_RETRY_LIMIT`
- `YTDLP_OUTPUT_ROOT`
- `YTDLP_SUBTITLE_LANGS`
- `CHANNEL_DISCOVERY_LIMIT`

Neu can them bien moi cho channel mode, hay them hop ly nhung giu ten ro nghia.

## 8. Output/runtime folders

Hay to chuc output trong `data/` theo huong co the tai su dung:

- `data/raw/youtube/`
- `data/raw/channel_discovery/`
- `data/processed/`
- `data/metadata/`
- `logs/`

Neu bai toan moi khong chi dung cho YouTube, hay doi ten folder nhung giu tinh than tach raw / processed / metadata.

## 9. API surface de xuat

Hay de xuat API toi thieu:

- `POST /api/v1/{module}/crawl-urls`
- `POST /api/v1/{module}/crawl-channel`
- `GET /api/v1/{module}/jobs`
- `GET /api/v1/{module}/jobs/{job_id}`
- `POST /api/v1/{module}/jobs/{job_id}/retry`
- `GET /api/v1/{module}/jobs/events`

Neu thay hop ly, hay tach them endpoint discovery preview cho channel.

## 10. Rang buoc ky thuat quan trong

- Khong viet mot ham khong lo vua discovery vua download vua export metadata
- Khong de route goi truc tiep `yt-dlp`
- Khong duplicate retry logic giua URL mode va channel mode
- Uu tien 1 service download chung, 1 service discovery rieng
- Ten method, step, va output field phai ro rang
- Viet code de co the test tung phan rieng

## 11. Dau ra toi muon tu ban

Hay tra ra:

1. Kien truc cap cao
2. Cau truc thu muc module
3. Danh sach class/function nen co
4. Workflow steps
5. Env vars
6. API surface
7. Pseudocode cho:
   - crawl tu URL
   - discover tu channel
   - failover proxy + cookie fallback
8. Neu co, de xuat skeleton code cho service layer

## 12. Bo sung quan trong

Neu codebase hien tai dang co `noplaylist=True` cho video URL mode, hay giu dieu do cho che do crawl URL.

Nhung voi channel mode:

- Hay tach phan discovery de lay URL video truoc
- Sau do moi dua tung video vao luong crawl URL mode
- Khong dung channel mode de download tat ca bang mot lenh duy nhat neu cach do lam kho retry, kho resume, hoac kho gan log/job state

Hay uu tien thiet ke de team co the mo rong sau nay sang:

- Crawl audio
- Crawl thumbnail
- Crawl subtitle
- Crawl metadata only
- Crawl channel dinh ky
```

## Ban Rut Gon

```text
Hay giup toi tai su dung `yt-dlp` trong mot du an FastAPI de ho tro 2 mode:

1. Crawl video tu danh sach URL
2. Discover video URL tu channel roi crawl tung video

Yeu cau:
- Service layer ro rang, khong goi `yt-dlp` truc tiep trong route
- Co retry, cookie fallback, proxy failover
- Discovery channel va download video phai tach rieng
- URL mode va channel mode phai dung chung download pipeline
- Output runtime tach raw / processed / metadata / logs
- Co API jobs va workflow steps ro rang

Hay tra ra:
1. Cau truc module
2. Function/service can co
3. Workflow steps
4. Env vars
5. API surface
6. Pseudocode cho URL mode va channel mode
```

## Goi Y Cach Dien Bien

- `{MODULE_NAME}`: vi du `video_ingest`, `youtube_crawler`, `media_pipeline`

## Ghi Chu Thuc Te Tu Repo Hien Tai

Prompt nay duoc viet dua tren nhung dac diem dang co trong repo:

- Crawl chinh hien tai di theo tung URL
- `yt-dlp` dang duoc goi trong service layer
- Da co cookie fallback va proxy failover
- Da co random delay, cooldown, retry va logging
- Kha nang mo rong tot nhat la them buoc discovery tu channel roi dung lai luong crawl URL

Voi repo hien tai, day la cach mo rong an toan hon viec dung ngay channel URL de download tat ca trong 1 lenh duy nhat.
