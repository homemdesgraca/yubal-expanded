// Must match backend validation in packages/api/src/yubal_api/schemas/jobs.py
// and core validation in packages/yubal/src/yubal/utils/url.py
export const YOUTUBE_URL_PATTERN =
  /^https?:\/\/(music\.youtube\.com\/(playlist\?list=|browse\/|watch\?v=)|(?:www\.|m\.)?youtube\.com\/(playlist\?list=|watch\?v=|shorts\/|live\/|embed\/|e\/|v\/|vi\/)|youtu\.be\/|(?:www\.)?youtube-nocookie\.com\/embed\/)[\w-]+/;

export const SOUNDCLOUD_URL_PATTERN =
  /^https?:\/\/(?:www\.)?soundcloud\.com\/[a-zA-Z0-9_-]+(\/sets\/[a-zA-Z0-9_-]+)?/;

export const SUPPORTED_URL_PATTERN = new RegExp(
  `^(?:${YOUTUBE_URL_PATTERN.source}|${SOUNDCLOUD_URL_PATTERN.source})$`
);

export function isValidUrl(url: string): boolean {
  return SUPPORTED_URL_PATTERN.test(url);
}
