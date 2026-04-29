// Workspace save/load client (Phase 7.3).
//
// Thin wrapper around fetch that mirrors the convention used by api.js:
//   - JSON body in/out
//   - Accept-Language forwarded so backend i18n is consistent
//   - Errors raised as ApiError with the response detail attached
//
// We re-use the ApiError class exported from api.js so callers can `instanceof`
// check both surfaces uniformly. The api.js `request()` helper is module-
// private, so we duplicate ~10 lines locally rather than refactor api.js.

import i18next from '../i18n/index.js';
import { ApiError } from './api.js';

/**
 * @typedef {Object} WorkspaceView
 * @property {number} id
 * @property {string} name
 * @property {Record<string, unknown>} state
 * @property {string} created_at  ISO 8601 UTC timestamp
 * @property {string} updated_at  ISO 8601 UTC timestamp
 */

/**
 * @typedef {Object} WorkspaceListResponse
 * @property {WorkspaceView[]} workspaces
 */

function currentLang() {
  return (i18next && i18next.language) || 'en';
}

/**
 * Internal fetch helper mirroring api.js semantics.
 *
 * @param {string} path
 * @param {{ method?: string, body?: unknown }} [opts]
 * @returns {Promise<unknown>}
 */
async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'Accept-Language': currentLang(),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // 204 No Content (DELETE success) -> nothing to parse.
  if (res.status === 204) {
    return undefined;
  }

  const text = await res.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? payload.detail
        : payload;
    throw new ApiError(`API ${res.status} ${res.statusText}`, {
      status: res.status,
      detail,
    });
  }
  return payload;
}

/**
 * @returns {Promise<WorkspaceListResponse>}
 */
export const listWorkspaces = () => request('/api/workspaces');

/**
 * @param {string} name
 * @returns {Promise<WorkspaceView>}
 */
export const getWorkspace = (name) =>
  request(`/api/workspaces/${encodeURIComponent(name)}`);

/**
 * Upsert by unique name — replaces the saved blob if `name` already exists,
 * otherwise inserts a new workspace.
 *
 * @param {string} name
 * @param {Record<string, unknown>} state
 * @returns {Promise<WorkspaceView>}
 */
export const saveWorkspace = (name, state) =>
  request('/api/workspaces', { method: 'PUT', body: { name, state } });

/**
 * @param {string} name
 * @returns {Promise<void>}
 */
export const deleteWorkspace = (name) =>
  request(`/api/workspaces/${encodeURIComponent(name)}`, { method: 'DELETE' });
