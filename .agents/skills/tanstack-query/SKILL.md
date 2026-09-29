---
name: tanstack-query
description: TanStack Query (React Query) v5 best practices for data fetching, caching, and mutations. Use when fetching server data with useQuery, setting up mutations with useMutation, configuring caching strategies, managing query keys, handling optimistic updates, invalidating queries, or integrating TanStack Query into a React/TypeScript project. Triggers on "React Query", "TanStack Query", "useQuery", "useMutation", "query keys", "stale time", "cache invalidation", "optimistic update", "prefetch", "infinite query".
---

# TanStack Query Best Practices

## Transit2Fog integration

- This is a React/Vite client using the existing API layer and generated types
  in `frontend/src/api/generated.ts`; keep `frontend/package-lock.json` authoritative.
  SSR, Suspense, new transports and global cache restructuring are optional,
  not prerequisites for ordinary feature fixes.
- Treat cache data as a client copy. The FastAPI database and confirmed path
  snapshots remain authoritative for saved journeys and GPX exports. Do not
  optimistically mark an ambiguous candidate as confirmed or bypass digest checks.
- Preserve intentional offline/loopback behavior and existing `networkMode`,
  retry and refetch settings unless the task calls for changing them. General
  defaults and "always" recommendations below do not justify unrelated rewrites.
- Include relevant mode, city, dataset/version and filter inputs in keys. Check
  affected lists, details, map/data status and export previews after mutations;
  invalidate what changed without indiscriminately clearing all caches.
- Reuse the available React and browser-testing skills for component performance
  and UI verification; use the sibling
  [Transit2Fog validation skill](../transit2fog-validation/SKILL.md) for domain checks.

Patterns and conventions for TanStack Query v5 data fetching, caching, and mutations in React/TypeScript projects.

## Core Mental Model

- **Server state vs client state** — TanStack Query manages server state (data from APIs). Do not duplicate it into `useState` or Redux; use those only for client state (UI state, form drafts).
- **Stale-while-revalidate** — Cached data is served immediately, then validated in the background. Users see data fast; freshness happens transparently.
- **Query keys = dependency arrays** — Every variable that affects fetching belongs in the key. When the key changes, TanStack Query refetches automatically.
- **Declarative over imperative** — Drive refetching by changing key values (state, filters, IDs), not by calling `refetch()` with new parameters.
- **Cache is the single source of truth** — The query cache is the authoritative store for all server state. Read from it; never copy it elsewhere.

## Quick Setup

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute — adjust per project
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <YourApp />
    </QueryClientProvider>
  )
}
```

Set `staleTime` globally instead of disabling individual refetch flags (`refetchOnMount`, `refetchOnWindowFocus`). Those flags are features — `staleTime` controls when they activate.

**Important:** Create the `QueryClient` outside the component body, or stabilize it with `useState`:

```tsx
// Inside a component — use useState to prevent new cache on every render
const [queryClient] = useState(() => new QueryClient({ /* ... */ }))
```

## Custom Hooks + queryOptions

Always wrap queries in custom hooks. Use `queryOptions` to co-locate key + function in a reusable, type-safe object:

```tsx
import { queryOptions, useQuery } from '@tanstack/react-query'

function todosQueryOptions(filters: TodoFilters) {
  return queryOptions({
    queryKey: ['todos', 'list', filters],
    queryFn: () => fetchTodos(filters),
  })
}

export function useTodos(filters: TodoFilters) {
  return useQuery(todosQueryOptions(filters))
}
```

`queryOptions` enables reuse across `useQuery`, `useSuspenseQuery`, `prefetchQuery`, `ensureQueryData`, and `invalidateQueries` — all from a single definition.

## Query Key Factories

Structure keys hierarchically from general to specific. Use `queryOptions` at fetchable levels, plain arrays at invalidation-only levels:

```ts
export const todoKeys = {
  all: ['todos'] as const,
  lists: () => [...todoKeys.all, 'list'] as const,
  list: (filters: TodoFilters) =>
    queryOptions({
      queryKey: [...todoKeys.lists(), filters] as const,
      queryFn: () => fetchTodos(filters),
    }),
  details: () => [...todoKeys.all, 'detail'] as const,
  detail: (id: number) =>
    queryOptions({
      queryKey: [...todoKeys.details(), id] as const,
      queryFn: () => fetchTodo(id),
    }),
}
```

Invalidation at different granularities:

```ts
// All todos (lists + details)
queryClient.invalidateQueries({ queryKey: todoKeys.all })

// All lists (any filter)
queryClient.invalidateQueries({ queryKey: todoKeys.lists() })

// One specific list
queryClient.invalidateQueries({ queryKey: todoKeys.list(filters).queryKey })

// All details
queryClient.invalidateQueries({ queryKey: todoKeys.details() })

// One specific detail
queryClient.invalidateQueries({ queryKey: todoKeys.detail(id).queryKey })
```

Co-locate key factories with their feature, not in a global `queryKeys.ts`.

## Dependent Queries

Two patterns for queries that depend on a value that may not exist yet:

**`skipToken` (preferred for TypeScript):**

```tsx
import { skipToken, useQuery } from '@tanstack/react-query'

export function useUser(userId: number | undefined) {
  return useQuery({
    queryKey: ['users', userId],
    queryFn: userId ? () => fetchUser(userId) : skipToken,
  })
}
```

**`enabled` option:**

```tsx
export function useUser(userId: number | undefined) {
  return useQuery({
    queryKey: ['users', userId],
    queryFn: () => fetchUser(userId!),
    enabled: !!userId,
  })
}
```

`skipToken` is better because TypeScript narrows `userId` inside the truthy branch — no non-null assertion needed.

## Data Transformations with select

Use `select` for derived data and partial subscriptions. Components only re-render when the selected value changes:

```tsx
// Only re-renders when the count changes
export function useTodoCount(filters: TodoFilters) {
  return useQuery({
    ...todosQueryOptions(filters),
    select: (data) => data.length,
  })
}
```

**Stabilize references** — inline `select` functions create new references every render:

```tsx
// Extract outside component (no deps)
const selectTodoCount = (data: Todo[]) => data.length

// Or wrap in useCallback (with deps)
const select = useCallback(
  (data: Todo[]) => data.filter((t) => t.priority >= minPriority),
  [minPriority],
)
```

## Status Checks: Data First

Check `data` before `error` to avoid replacing stale data with an error screen during background refetches:

```tsx
const todos = useTodos(filters)

if (todos.data) return <TodoList todos={todos.data} />
if (todos.error) return <ErrorMessage error={todos.error} />
return <Loading />
```

Background refetch failures set `error` while stale `data` remains available. Checking error first hides perfectly good cached data.

## Mutations

Use `useMutation` + query invalidation as the default strategy:

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'

export function useAddTodo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (newTodo: NewTodo) => createTodo(newTodo),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
    },
  })
}
```

**Return the promise** from `invalidateQueries` in `onSuccess` to keep the mutation in loading state until the refetch completes.

### Mutation strategy decision table

| Strategy | When | Complexity |
|----------|------|------------|
| Invalidation | Default for all mutations | Low |
| Direct cache update | Response returns full updated entity | Medium |
| Optimistic update | Instant feedback essential, rarely fails | High — see [optimistic-updates.md](references/optimistic-updates.md) |

### Callback separation

Place query/cache logic in `useMutation` callbacks and UI logic in `mutate()` callbacks:

```tsx
// Hook — cache concerns
const mutation = useMutation({
  mutationFn: updateTodo,
  onSuccess: () => {
    return queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
  },
})

// Component — UI concerns
mutation.mutate(updatedTodo, {
  onSuccess: () => {
    toast.success('Saved!')
    navigate('/todos')
  },
})
```

**Prefer `mutate` over `mutateAsync`.** `mutate` handles errors automatically. Only use `mutateAsync` when composing multiple dependent mutations.

**Pass multiple variables as a single object** — `mutate` accepts only one argument:

```tsx
mutation.mutate({ id: 1, title: 'Updated' }) // correct
```

## TypeScript

- **Let inference work.** Type the `queryFn` return, not `useQuery` generics. Avoid `useQuery<Todo>()`.
- **Validate at the boundary.** Use Zod in `queryFn` for runtime type safety:

  ```tsx
  const todoSchema = z.object({ id: z.number(), title: z.string(), done: z.boolean() })

  const fetchTodo = async (id: number) => {
    const res = await fetch(`/api/todos/${id}`)
    if (!res.ok) throw new Error('Failed to fetch')
    return todoSchema.parse(await res.json())
  }
  ```

- **Use `skipToken`** for type-safe dependent queries (narrows types without `!`).
- **Register global error types** via module augmentation:

  ```tsx
  declare module '@tanstack/react-query' {
    interface Register {
      defaultError: AxiosError
    }
  }
  ```

- **Don't destructure** if you need type narrowing — `const query = useTodos()` then `if (query.isSuccess)` narrows `query.data`.

## Error Handling

Three complementary strategies:

### 1. Per-query error property (inline)

```tsx
if (query.error) return <ErrorMessage error={query.error} />
```

### 2. Error boundaries with throwOnError

Use a function for granular control — propagate 5xx to boundaries, handle 4xx locally:

```tsx
useQuery({
  ...todosQueryOptions(filters),
  throwOnError: (error) => error.status >= 500,
})
```

### 3. Global toasts via QueryCache.onError

Show toasts only for background refetch failures (stale data exists):

```tsx
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.state.data !== undefined) {
        toast.error(`Background update failed: ${error.message}`)
      }
    },
  }),
})
```

### Fetch API gotcha

`fetch` does not reject on 4xx/5xx. You must throw manually:

```tsx
const res = await fetch(url)
if (!res.ok) throw new Error(`Request failed: ${res.status}`)
return res.json()
```

## Anti-Patterns

### 1. Copying server state to useState

```tsx
// Don't
const { data } = useTodos()
const [todos, setTodos] = useState(data) // stale copy, never updates

// Do — use query data directly
const { data: todos } = useTodos()
```

### 2. Imperative refetching in useEffect

```tsx
// Don't
useEffect(() => { refetch() }, [filters])

// Do — put filters in the query key
useQuery({ queryKey: ['todos', filters], queryFn: () => fetchTodos(filters) })
```

### 3. Disabling refetch flags

```tsx
// Don't
useQuery({ queryKey: ['todos'], queryFn: fetchTodos, refetchOnWindowFocus: false, refetchOnMount: false })

// Do — set staleTime to control freshness
useQuery({ queryKey: ['todos'], queryFn: fetchTodos, staleTime: 1000 * 60 * 5 })
```

### 4. Using query cache as local state manager

Don't call `setQueryData` for client-only state. Background refetches overwrite manual cache writes.

### 5. Object rest destructuring

```tsx
// Don't — defeats tracked queries, re-renders on every field change
const { data, ...rest } = useQuery(...)

// Do — destructure only what you need
const { data, isPending } = useQuery(...)
```

### 6. Inline selectors without stable references

```tsx
// Don't — new function every render
useQuery({ ...opts, select: (d) => d.filter(expensiveCheck) })

// Do — extract or useCallback
const select = useCallback((d: Todo[]) => d.filter(expensiveCheck), [])
```

### 7. Manual generic specification on useQuery

```tsx
// Don't
useQuery<Todo[], Error, Todo[], ['todos']>({ ... })

// Do — let inference flow from queryFn return type
useQuery({ queryKey: ['todos'], queryFn: fetchTodos })
```

### 8. Checking error before data

```tsx
// Don't — hides cached data on background refetch error
if (error) return <Error />
if (data) return <Data />

// Do — show cached data even when background refetch fails
if (data) return <Data />
if (error) return <Error />
```

## Configuration Reference

| Option | Default | Purpose |
|--------|---------|---------|
| `staleTime` | `0` | How long data is considered fresh (ms). Fresh data is never refetched. |
| `gcTime` | `5 min` | How long inactive cache entries are kept before garbage collection. |
| `retry` | `3` | Number of retry attempts on failure. Set `false` in tests. |
| `enabled` | `true` | Set `false` to disable automatic fetching. Prefer `skipToken`. |
| `refetchOnWindowFocus` | `true` | Refetch stale queries on window focus. Controlled by `staleTime`. |
| `throwOnError` | `false` | Propagate errors to nearest error boundary. Accepts a function. |
| `networkMode` | `'online'` | `'online'` / `'always'` / `'offlineFirst'`. Controls fetch behavior when offline. |
| `placeholderData` | — | Shown while real data loads. Use `keepPreviousData` for pagination. |

## Specialized Guides

Open these only when the task requires them:

- [Optimistic Updates](references/optimistic-updates.md) — When implementing optimistic UI, direct cache manipulation, or concurrent mutations
- [Testing](references/testing.md) — When writing tests for queries, mutations, or components using TanStack Query
- [Suspense & SSR](references/suspense-and-ssr.md) — When using `useSuspenseQuery`, prefetching in loaders, or server-side rendering
- [Realtime & Advanced Patterns](references/realtime-and-advanced.md) — When integrating WebSockets, infinite scrolling, offline support, or form state management
