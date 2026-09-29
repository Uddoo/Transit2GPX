# Realtime & Advanced Patterns

- [WebSocket Integration](#websocket-integration)
- [Infinite Queries](#infinite-queries)
- [Offline Support](#offline-support)
- [Forms Integration](#forms-integration)
- [Automatic Global Invalidation](#automatic-global-invalidation)
- [Pagination with keepPreviousData](#pagination-with-keeppreviousdata)

## WebSocket Integration

Use HTTP for initial data fetching and WebSockets only for triggering updates. Two strategies, from simplest to most involved:

### Strategy 1: Event-based invalidation (recommended)

Send lightweight events from the server indicating which entity changed. Let TanStack Query handle refetching:

```tsx
import { useQueryClient } from '@tanstack/react-query'

function useRealtimeInvalidation(url: string) {
  const queryClient = useQueryClient()

  useEffect(() => {
    const ws = new WebSocket(url)

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      // e.g., { entity: ['todos'], id: 5 }
      const queryKey = [...data.entity, data.id].filter(Boolean)
      queryClient.invalidateQueries({ queryKey })
    }

    return () => ws.close()
  }, [queryClient, url])
}
```

**Set `staleTime: Infinity`** when WebSockets handle freshness — prevents redundant HTTP refetches on window focus or mount:

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: Infinity },
  },
})
```

Invalidation is smart — only active (mounted) queries refetch. Inactive queries are just marked stale.

### Strategy 2: Partial cache updates

For high-frequency updates where a full refetch is too expensive:

```tsx
ws.onmessage = (event) => {
  const { entity, id, payload } = JSON.parse(event.data)

  queryClient.setQueriesData({ queryKey: entity }, (oldData: any) => {
    if (!oldData) return oldData
    const update = (item: any) =>
      item.id === id ? { ...item, ...payload } : item
    return Array.isArray(oldData) ? oldData.map(update) : update(oldData)
  })
}
```

`setQueriesData` updates all matching cache entries at once (lists and details). Use this for data like live scores, stock prices, or typing indicators.

## Infinite Queries

`useInfiniteQuery` manages paginated data that accumulates (load more, infinite scroll).

### Basic setup

```tsx
import { useInfiniteQuery } from '@tanstack/react-query'

function useInfiniteTodos() {
  return useInfiniteQuery({
    queryKey: ['todos', 'infinite'],
    queryFn: ({ pageParam }) => fetchTodos({ cursor: pageParam, limit: 20 }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
}
```

**Required options:**

- `initialPageParam` — Starting page parameter (required in v5)
- `getNextPageParam` — Returns the next page param, or `undefined` when there are no more pages

### Rendering

```tsx
function TodoInfiniteList() {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteTodos()

  return (
    <>
      {data?.pages.flatMap((page) =>
        page.items.map((todo) => <TodoItem key={todo.id} todo={todo} />),
      )}

      <button
        onClick={() => fetchNextPage()}
        disabled={!hasNextPage || isFetchingNextPage}
      >
        {isFetchingNextPage ? 'Loading more...' : hasNextPage ? 'Load More' : 'No more items'}
      </button>
    </>
  )
}
```

### Prefetching the next page

```tsx
const { data, hasNextPage } = useInfiniteTodos()

// Prefetch next page when current page renders
useEffect(() => {
  if (hasNextPage) {
    queryClient.prefetchInfiniteQuery({
      queryKey: ['todos', 'infinite'],
      queryFn: ({ pageParam }) => fetchTodos({ cursor: pageParam, limit: 20 }),
      initialPageParam: 0,
      getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
      pages: (data?.pages.length ?? 0) + 1,
    })
  }
}, [data, hasNextPage, queryClient])
```

### Bi-directional infinite queries

For chat-like UIs where you can scroll in both directions:

```tsx
useInfiniteQuery({
  queryKey: ['messages'],
  queryFn: ({ pageParam }) => fetchMessages({ cursor: pageParam }),
  initialPageParam: currentMessageId,
  getNextPageParam: (lastPage) => lastPage.nextCursor,
  getPreviousPageParam: (firstPage) => firstPage.prevCursor,
})
// Use fetchPreviousPage() and hasPreviousPage for upward scrolling
```

**Key behavior:** When refetching, all existing pages are re-fetched sequentially. This ensures data consistency but means refetches are proportional to loaded pages.

## Offline Support

TanStack Query has three network modes that control fetch behavior when offline:

| Mode | Behavior | Use for |
|------|----------|---------|
| `online` (default) | Queries pause when offline, resume when online | Standard HTTP fetching |
| `always` | Network status ignored — queries always fire | Non-HTTP async (IndexedDB, Web Workers) |
| `offlineFirst` | First request fires regardless, retries pause if offline | Service workers, HTTP cache headers |

### fetchStatus

Use `fetchStatus` alongside `status` for complete state awareness:

```tsx
const { status, fetchStatus, data } = useQuery(todoKeys.list(filters))

// status: 'success' + fetchStatus: 'paused'
// = have cached data, background refetch paused (offline)

// status: 'pending' + fetchStatus: 'paused'
// = no cached data, fetch paused (offline) — show offline indicator

if (fetchStatus === 'paused') {
  return <OfflineBanner />
}
```

### Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      networkMode: 'offlineFirst', // or 'online' | 'always'
    },
    mutations: {
      networkMode: 'offlineFirst',
    },
  },
})
```

## Forms Integration

Forms represent the boundary between server state and client state. TanStack Query fetches the initial data; local state owns the editing process; a mutation submits changes.

### Pattern: Query for initial data, local state for edits, mutation for submit

```tsx
function EditTodoForm({ id }: { id: number }) {
  const { data: todo } = useSuspenseQuery(todoKeys.detail(id))

  return <TodoForm todo={todo} />
}

function TodoForm({ todo }: { todo: Todo }) {
  const { register, handleSubmit } = useForm({ defaultValues: todo })
  const mutation = useUpdateTodo()

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <input {...register('title')} />
      <button type="submit" disabled={mutation.isPending}>Save</button>
    </form>
  )
}
```

**Key: Separate the data-fetching wrapper from the form component.** This ensures `defaultValues` are set with real data, not `undefined`, because the form only mounts after Suspense resolves.

### Prevent stale overwrites during editing

Set `staleTime: Infinity` on the query to prevent background refetches from overwriting user edits:

```tsx
useQuery({
  ...todoKeys.detail(id),
  staleTime: Infinity, // Don't refetch while user is editing
})
```

### Invalidate + reset on submit

```tsx
const mutation = useMutation({
  mutationFn: updateTodo,
  onSuccess: () => {
    return queryClient.invalidateQueries({ queryKey: todoKeys.detail(id).queryKey })
  },
})

// In component
mutation.mutate(values, {
  onSuccess: () => reset(), // Reset form after cache is updated
})
```

## Automatic Global Invalidation

Instead of manually invalidating in every mutation's `onSuccess`, use a `MutationCache` callback:

### Fire-and-forget: Invalidate everything on any mutation success

```tsx
const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  }),
})
```

This is a reasonable starting point — slightly over-fetches but never misses a needed refetch. A moderate `staleTime` (~2 minutes) mitigates unnecessary network traffic.

### Targeted: Use mutationKey for scoped invalidation

```tsx
const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onSuccess: (_data, _variables, _context, mutation) => {
      queryClient.invalidateQueries({
        queryKey: mutation.options.mutationKey,
      })
    },
  }),
})

// Usage — mutationKey drives invalidation
useMutation({
  mutationFn: updateTodo,
  mutationKey: ['todos'], // Invalidates all queries starting with ['todos']
})
```

### Declarative: Use meta for per-mutation invalidation lists

```tsx
// Type the meta
declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: {
      invalidates?: Array<QueryKey>
    }
  }
}

// Global handler
const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onSuccess: (_data, _variables, _context, mutation) => {
      const invalidates = mutation.meta?.invalidates
      if (invalidates) {
        invalidates.forEach((key) =>
          queryClient.invalidateQueries({ queryKey: key }),
        )
      }
    },
  }),
})

// Usage
useMutation({
  mutationFn: updateLabel,
  meta: { invalidates: [['issues'], ['labels']] },
})
```

### Excluding static queries

Queries with `staleTime: Infinity` should be excluded from blanket invalidation:

```tsx
queryClient.invalidateQueries({
  predicate: (query) => query.staleTime !== Number.POSITIVE_INFINITY,
})
```

## Pagination with keepPreviousData

Use `placeholderData: keepPreviousData` to show the current page while the next page loads:

```tsx
import { keepPreviousData, useQuery } from '@tanstack/react-query'

function PaginatedTodos() {
  const [page, setPage] = useState(1)

  const { data, isPlaceholderData } = useQuery({
    queryKey: ['todos', 'list', page],
    queryFn: () => fetchTodos({ page }),
    placeholderData: keepPreviousData,
  })

  return (
    <div style={{ opacity: isPlaceholderData ? 0.5 : 1 }}>
      {data?.items.map((todo) => <TodoItem key={todo.id} todo={todo} />)}

      <button
        onClick={() => setPage((p) => p - 1)}
        disabled={page === 1}
      >
        Previous
      </button>

      <button
        onClick={() => setPage((p) => p + 1)}
        disabled={isPlaceholderData || !data?.hasMore}
      >
        Next
      </button>
    </div>
  )
}
```

**Key points:**

- `isPlaceholderData` is `true` while showing the previous page's data — use it to dim the UI or disable forward navigation.
- Disable the "Next" button when `isPlaceholderData` is true to prevent skipping pages.
- Each page gets its own cache entry, so going back is instant.

### Prefetching the next page

```tsx
const queryClient = useQueryClient()

useEffect(() => {
  if (!isPlaceholderData && data?.hasMore) {
    queryClient.prefetchQuery({
      queryKey: ['todos', 'list', page + 1],
      queryFn: () => fetchTodos({ page: page + 1 }),
    })
  }
}, [data, isPlaceholderData, page, queryClient])
```
