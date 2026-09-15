/**
 * 从后端 OpenAPI schema 生成前端类型（AGENTS.md §4.3 硬性规则 2）。
 *
 * 契约唯一来源是后端 `/openapi.json`；**禁止**手写第二份类型定义。
 * 生成物 `src/api/schema.d.ts` 不进版本库（根 `.gitignore` 已忽略）。
 *
 * 取 schema 的两条路径：
 *   1. 在线：`GET {API_ORIGIN}/openapi.json`（默认 http://127.0.0.1:8000，可用环境变量覆盖）；
 *   2. 离线回退：仓库内的 `openapi.snapshot.json`（由 `--update-snapshot` 生成）。
 *      为什么需要回退：`pnpm build` 是 M4 验收命令，不应因为"后端没起"而无法构建；
 *      快照是**后端产物的副本**而非手写类型，且在线可用时永远优先取实时 schema。
 *
 * 用法：
 *   node scripts/gen-api-types.mjs                  # 在线优先，失败回退快照
 *   node scripts/gen-api-types.mjs --update-snapshot # 从在线 schema 刷新快照并生成类型
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import openapiTS, { astToString } from 'openapi-typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const OUT = path.join(root, 'src', 'api', 'schema.d.ts')
const SNAPSHOT = path.join(root, 'openapi.snapshot.json')

const API_ORIGIN = (process.env.API_ORIGIN || process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(
  /\/+$/,
  '',
)
const UPDATE_SNAPSHOT = process.argv.includes('--update-snapshot')
const TIMEOUT_MS = Number(process.env.API_ORIGIN_TIMEOUT_MS || 8000)

const HEADER = `/**
 * 自动生成，请勿手工修改。
 * 来源：后端 OpenAPI schema（AGENTS.md §4.3 硬性规则 2：契约唯一来源）。
 * 重新生成：\`pnpm gen:api\`（后端在跑时取实时 schema，否则回退 openapi.snapshot.json）。
 * 本文件已被 .gitignore 忽略，不进版本库。
 */
`

async function fetchLive() {
  const url = `${API_ORIGIN}/openapi.json`
  const response = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) })
  if (!response.ok) throw new Error(`${url} → HTTP ${response.status}`)
  const schema = await response.json()
  if (!schema || !schema.paths) throw new Error(`${url} 返回的不是 OpenAPI 文档`)
  return { schema, origin: url }
}

async function main() {
  let schema = null
  let origin = ''
  let liveError = ''

  // 在线 schema 永远优先：它才是"契约唯一来源"，快照只是不可用时的回退。
  try {
    const live = await fetchLive()
    schema = live.schema
    origin = live.origin
  } catch (error) {
    liveError = error instanceof Error ? error.message : String(error)
  }

  if (schema && UPDATE_SNAPSHOT) {
    await writeFile(SNAPSHOT, `${JSON.stringify(schema, null, 2)}\n`, 'utf8')
    console.log(`[gen:api] 快照已刷新 → ${path.relative(root, SNAPSHOT)}`)
  }

  if (!schema) {
    if (!existsSync(SNAPSHOT)) {
      console.error(
        `[gen:api] 无法获取实时 OpenAPI（${liveError}），且不存在 ${path.relative(root, SNAPSHOT)}。\n` +
          `[gen:api] 请先启动后端：cd backend && ..\\backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000`,
      )
      process.exit(1)
    }
    schema = JSON.parse(await readFile(SNAPSHOT, 'utf8'))
    origin = `${path.relative(root, SNAPSHOT)}（离线回退；原因：${liveError}）`
  }

  const ast = await openapiTS(schema, { alphabetize: true })
  await mkdir(path.dirname(OUT), { recursive: true })
  await writeFile(OUT, HEADER + astToString(ast), 'utf8')

  const pathCount = Object.keys(schema.paths || {}).length
  const schemaCount = Object.keys(schema.components?.schemas || {}).length
  console.log(
    `[gen:api] ${pathCount} 个端点 / ${schemaCount} 个 schema ← ${origin}\n` +
      `[gen:api] 已写入 ${path.relative(root, OUT)}`,
  )
}

main().catch((error) => {
  console.error('[gen:api] 生成失败：', error)
  process.exit(1)
})
