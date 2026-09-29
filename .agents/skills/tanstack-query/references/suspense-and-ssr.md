# Suspense & SSR

- [useSuspenseQuery](#usesuspensequery)
- [Avoiding Suspense Waterfalls](#avoiding-suspense-waterfalls)
- [Prefetching Strategies](#prefetching-strategies)
- [React Router Integration](#react-router-integration)
- [Cache Seeding](#cache-seeding)
- [Placeholder vs Initial Data](#placeholder-vs-initial-data)

## useSuspenseQuery

`useSuspenseQuery` suspends the component until data is available. The result type has `data` always defined — no `undefined` checks needed:

```tsx
import { useSuspenseQuery } from '@tanstack/react-query'

function TodoList({ filters }: { filters: TodoFilters }) {
  const { data } = useSuspenseQuery(todoKeys.list(filters))
  // data is Todo[], never undefined
  return <ul>{data.map((t) => <li key={t.id}>{t.title}</li>)}</ul>
}
```

Wrap the component in a `<Suspense>` boundary with a fallback:

```tsx
<Suspense fallback={<Loading />}>
  <TodoList filters={filters} />
</Suspense>
```

**Key differences from `useQuery`:**

- `data` is always defined (no `isPending` / `isLoading` checks)
- No `enabled` option or `skipToken` — the query always runs
- Errors propagate to the nearest error boundary (no local error state)
- `placeholderData` is not supported

## Avoiding Suspense Waterfalls

Multiple `useSuspenseQuery` calls in the same component execute sequentially — the second suspends only after the first resolves:

```tsx
// Waterfall — second query waits for first
function TodoDetail({ id }: { id: number }) {
  const { data: todo } = useSuspenseQuery(todoKeys.detail(id))
  const { data: comments } = useSuspenseQuery(commentKeys.list(id))
  // ...
}
```

**Fix: One suspense query per component.**

Split into sibling components under a shared `<Suspense>` boundary:

```tsx
function TodoDetail({ id }: { id: number }) {
  return (
    <Suspense fallback={<Loading />}>
      <TodoContent id={id} />
      <TodoComments id={id} />
    </Suspense>
  )
}

function TodoContent({ id }: { id: number }) {
  const { data } = useSuspenseQuery(todoKeys.detail(id))
  return <h1>{data.title}</h1>
}

function TodoComments({ id }: { id: number }) {
  const { data } = useSuspenseQuery(commentKeys.list(id))
  return <CommentList comments={data} />
}
```

**Alternative: Prefetch before render** — see next section.

## Prefetching Strategies

Prefetching populates the cache before a component mounts, eliminating loading states and waterfalls.

### prefetchQuery

Fires a fetch if the cache is empty or stale. Does not return the data — just warms the cache:

```tsx
await queryClient.prefetchQuery(todoKeys.detail(id))
```

### ensureQueryData

Returns cached data if available, otherwise fetches. Useful when you need the data in the calling context:

```tsx
const todos = await queryClient.ensureQueryData(todoKeys.list(filters))
```

### When to prefetch

- **Route loaders** — Prefetch before navigation completes (see React Router section)
- **Hover/focus handlers** — Prefetch on user intent signals
- **Parent components** — Prefetch child data before children mount

```tsx
// Prefetch on hover
function TodoLink({ id }: { id: number }) {
  const queryClient = useQueryClient()
  return (
    <Link
      to={`/todos/${id}`}
      onMouseEnter={() => queryClient.prefetchQuery(todoKeys.detail(id))}
    >
      View Todo
    </Link>
  )
}
```

## React Router Integration

React Router loaders run before rendering. Use them to start fetches early. TanStack Query handles caching and background updates.

### Loader pattern

Pass `queryClient` to the loader via a curried function (loaders are not hooks):

```tsx
// routes/todos.tsx
import { todoKeys } from '../queries/todos'

export const todosLoader = (queryClient: QueryClient) =>
  async function loader({ params }: LoaderFunctionArgs) {
    // Return cached data or fetch — never refetch if fresh
    return queryClient.ensureQueryData(todoKeys.list({ status: 'all' }))
  }
```

### Router setup

```tsx
const queryClient = new QueryClient({ /* ... */ })

const router = createBrowserRouter([
  {
    path: '/todos',
    element: <TodoList />,
    loader: todosLoader(queryClient),
  },
])
```

### Using loader data as initialData

The loader guarantees data exists. Pass it as `initialData` to eliminate `undefined` from the component's perspective:

```tsx
import { useLoaderData } from 'react-router-dom'

function TodoList() {
  const loaderData = useLoaderData() as Todo[]

  const { data } = useQuery({
    ...todoKeys.list({ status: 'all' }),
    initialData: loaderData,
  })

  // data is always defined on first render
}
```

### Awaiting invalidation in actions

Control whether the user sees loading during invalidation:

```tsx
// Redirect immediately — refetch happens in background
export async function action({ request }: ActionFunctionArgs) {
  await createTodo(formData)
  queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
  return redirect('/todos')
}

// Wait for fresh data — user sees loading but gets fresh data on arrival
export async function action({ request }: ActionFunctionArgs) {
  await createTodo(formData)
  await queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
  return redirect('/todos')
}
```

## Cache Seeding

Populate detail caches from list data to avoid loading states when navigating from list to detail views.

### Pull approach — initialData from cache

Seed the detail query from the list cache on demand:

```tsx
export function useTodoDetail(id: number) {
  const queryClient = useQueryClient()

  return useQuery({
    ...todoKeys.detail(id),
    initialData: () =>
      queryClient
        .getQueryData(todoKeys.list({ status: 'all' }).queryKey)
        ?.find((todo: Todo) => todo.id === id),
    initialDataUpdatedAt: () =>
      queryClient.getQueryState(todoKeys.list({ status: 'all' }).queryKey)?.dataUpdatedAt,
  })
}
```

**Always provide `initialDataUpdatedAt`** — without it, seeded data is treated as "just fetched" and `staleTime` calculations are wrong. The query won't background-refetch even if the list data is old.

### Push approach — setQueryData in queryFn

Proactively populate detail caches after fetching a list:

```tsx
const todosListOptions = (filters: TodoFilters) =>
  queryOptions({
    queryKey: ['todos', 'list', filters],
    queryFn: async () => {
      const todos = await fetchTodos(filters)
      // Push each item into the detail cache
      todos.forEach((todo) => {
        queryClient.setQueryData(todoKeys.detail(todo.id).queryKey, todo)
      })
      return todos
    },
  })
```

**Trade-offs:**

| | Pull (initialData) | Push (setQueryData) |
|---|---|---|
| When it runs | On demand, when detail query mounts | Immediately after list fetch |
| Cache entries | Only for items the user visits | For all items in the list |
| Staleness tracking | Requires `initialDataUpdatedAt` | Automatic (uses current time) |
| Best for | Large lists, occasional detail views | Small lists, likely detail navigation |

## Placeholder vs Initial Data

| | `placeholderData` | `initialData` |
|---|---|---|
| **Cache level** | Observer (per-component) | Cache (shared across components) |
| **Status** | `isPending` while shown | `isSuccess` immediately |
| **On error** | Disappears — `data` becomes `undefined` | Persists — remains visible in `error` state |
| **Staleness** | N/A — always triggers background fetch | Respects `staleTime` (pair with `initialDataUpdatedAt`) |
| **Use case** | Fake-it-till-you-make-it (skeletons, previous page data) | Real data from another cache entry |

### placeholderData examples

```tsx
// Static placeholder
useQuery({
  queryKey: ['todo', id],
  queryFn: () => fetchTodo(id),
  placeholderData: { id: 0, title: 'Loading...', done: false },
})

// Keep previous data during pagination
import { keepPreviousData } from '@tanstack/react-query'

useQuery({
  queryKey: ['todos', page],
  queryFn: () => fetchTodos(page),
  placeholderData: keepPreviousData,
})
// Use isPlaceholderData to style stale page data differently
```

### initialData example

```tsx
// Seed from another cache entry
useQuery({
  queryKey: ['todo', id],
  queryFn: () => fetchTodo(id),
  initialData: () =>
    queryClient.getQueryData(['todos', 'list'])?.find((t) => t.id === id),
  initialDataUpdatedAt: () =>
    queryClient.getQueryState(['todos', 'list'])?.dataUpdatedAt,
})
```
