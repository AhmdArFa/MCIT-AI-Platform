'use client'

import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { formatTokens, usageApi } from '@/lib/api/studio'

export default function UsagePage() {
  const { data: rows = [], dataUpdatedAt } = useQuery({ queryKey: ['usage-summary'], queryFn: usageApi.summary, refetchInterval: 3000 })
  const { data: recent = [] } = useQuery({ queryKey: ['usage-recent'], queryFn: () => usageApi.recent(30), refetchInterval: 3000 })
  const totals = rows.reduce(
    (a, r) => ({ requests: a.requests + r.requests, input: a.input + r.input_tokens, output: a.output + r.output_tokens, reasoning: a.reasoning + r.reasoning_tokens }),
    { requests: 0, input: 0, output: 0, reasoning: 0 }
  )

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
          <div className="flex items-end justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl font-semibold tracking-tight">My usage</h1>
              <p className="text-sm text-muted-foreground">Your own model calls only. Token counts are the ones each provider reports.</p>
            </div>
            <span className="text-xs text-muted-foreground">Updated {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : '—'}</span>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ['Requests', totals.requests.toLocaleString()],
              ['Input tokens', formatTokens(totals.input)],
              ['Output tokens', formatTokens(totals.output)],
              ['Reasoning tokens', formatTokens(totals.reasoning)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-xl border bg-card p-4">
                <div className="text-xs text-muted-foreground">{k}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{v}</div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Model</th>
                  <th className="px-4 py-2.5 font-medium">Provider</th>
                  <th className="px-4 py-2.5 text-right font-medium">Requests</th>
                  <th className="px-4 py-2.5 text-right font-medium">Input</th>
                  <th className="px-4 py-2.5 text-right font-medium">Output</th>
                  <th className="px-4 py-2.5 text-right font-medium">Reasoning</th>
                  <th className="px-4 py-2.5 text-right font-medium">Errors</th>
                  <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                  <th className="px-4 py-2.5 text-right font-medium">Last used</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-10 text-center text-sm text-muted-foreground"><Gauge className="mx-auto mb-2 h-5 w-5" />No model calls yet</td></tr>
                )}
                {rows.map((r) => (
                  <tr key={`${r.provider}-${r.model}`} className="border-t">
                    <td className="px-4 py-2.5 font-medium">{r.model}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{r.provider}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{r.requests.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{r.input_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{r.output_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{r.reasoning_tokens.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{r.errors}</td>
                    <td className="px-4 py-2.5 text-right text-muted-foreground" title="Provider pricing is not configured">{r.provider === 'ollama' || r.provider === 'openai_compatible' ? 'Local, no charge' : 'No price set'}</td>
                    <td className="px-4 py-2.5 text-right text-muted-foreground">{r.last_used ? new Date(r.last_used).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="text-sm font-medium">Recent calls</h2>
            <div className="overflow-hidden rounded-xl border">
              <table className="w-full text-xs">
                <tbody>
                  {recent.map((e, i) => (
                    <tr key={i} className="border-t first:border-t-0">
                      <td className="px-4 py-2 text-muted-foreground">{new Date(e.created).toLocaleTimeString()}</td>
                      <td className="px-4 py-2">{e.model}</td>
                      <td className="px-4 py-2 capitalize text-muted-foreground">{e.feature}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{e.input_tokens.toLocaleString()} in</td>
                      <td className="px-4 py-2 text-right tabular-nums">{e.output_tokens.toLocaleString()} out</td>
                      <td className="px-4 py-2 text-right">{e.error ? <span className="text-destructive">{e.error}</span> : 'ok'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
