# Testing

- [Test Setup](#test-setup)
- [createWrapper Helper](#createwrapper-helper)
- [Testing Custom Hooks](#testing-custom-hooks)
- [Testing Components](#testing-components)
- [MSW Integration](#msw-integration)
- [Common Gotchas](#common-gotchas)

## Test Setup

Create a fresh `QueryClient` for every test to ensure isolation. Override defaults that cause problems in tests:

```tsx
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,      // Retries cause timeouts in tests
        gcTime: Infinity,  // Prevent garbage collection during test
      },
    },
  })
}
```

**Why these overrides:**

- `retry: false` — Default 3 retries with exponential backoff causes tests to timeout waiting for the final failure.
- `gcTime: Infinity` — Prevents cache entries from being collected mid-test, which causes flaky assertions.

**Never share a `QueryClient` across tests.** Parallel test execution + shared cache = flaky tests.

## createWrapper Helper

Build a reusable wrapper for `renderHook` and `render`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

function createWrapper() {
  const queryClient = createTestQueryClient()
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    )
  }
}
```

Usage:

```tsx
const { result } = renderHook(() => useTodos(), {
  wrapper: createWrapper(),
})
```

Create a new wrapper per test — each call creates a fresh `QueryClient`.

## Testing Custom Hooks

Use `renderHook` from `@testing-library/react` with `waitFor` for async assertions:

```tsx
import { renderHook, waitFor } from '@testing-library/react'

test('useTodos returns todo list', async () => {
  const { result } = renderHook(() => useTodos({ status: 'all' }), {
    wrapper: createWrapper(),
  })

  // Wait for the query to resolve
  await waitFor(() => {
    expect(result.current.isSuccess).toBe(true)
  })

  expect(result.current.data).toHaveLength(3)
  expect(result.current.data?.[0].title).toBe('Buy groceries')
})
```

### Testing mutations

```tsx
test('useAddTodo creates a todo and invalidates list', async () => {
  const { result } = renderHook(() => useAddTodo(), {
    wrapper: createWrapper(),
  })

  result.current.mutate({ title: 'New todo' })

  await waitFor(() => {
    expect(result.current.isSuccess).toBe(true)
  })
})
```

### Testing dependent queries

```tsx
test('useUser is disabled when id is undefined', () => {
  const { result } = renderHook(() => useUser(undefined), {
    wrapper: createWrapper(),
  })

  // Query should not fire — status stays pending, no fetch
  expect(result.current.fetchStatus).toBe('idle')
  expect(result.current.isPending).toBe(true)
})
```

## Testing Components

Wrap components in the provider and assert on loading → success → error states:

```tsx
import { render, screen, waitFor } from '@testing-library/react'

test('TodoList renders todos after loading', async () => {
  render(<TodoList />, { wrapper: createWrapper() })

  // Loading state
  expect(screen.getByText('Loading...')).toBeInTheDocument()

  // Wait for data
  await waitFor(() => {
    expect(screen.getByText('Buy groceries')).toBeInTheDocument()
  })
})

test('TodoList shows error on failure', async () => {
  // MSW handler returns 500 for this test
  server.use(
    http.get('/api/todos', () => {
      return HttpResponse.json({ message: 'Server error' }, { status: 500 })
    }),
  )

  render(<TodoList />, { wrapper: createWrapper() })

  await waitFor(() => {
    expect(screen.getByText(/error/i)).toBeInTheDocument()
  })
})
```

## MSW Integration

Mock at the network level with [Mock Service Worker](https://mswjs.io/), not at the hook level. This tests the full data flow including `queryFn` logic, error handling, and response parsing.

### Setup

```tsx
// src/mocks/handlers.ts
import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/todos', () => {
    return HttpResponse.json([
      { id: 1, title: 'Buy groceries', done: false },
      { id: 2, title: 'Walk dog', done: true },
      { id: 3, title: 'Read book', done: false },
    ])
  }),

  http.post('/api/todos', async ({ request }) => {
    const body = await request.json()
    return HttpResponse.json({ id: 4, ...body, done: false }, { status: 201 })
  }),
]

// src/mocks/server.ts
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
```

### Test lifecycle

```tsx
// vitest.setup.ts (or jest equivalent)
import { server } from './mocks/server'

beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

### Per-test overrides

```tsx
test('handles server error', async () => {
  server.use(
    http.get('/api/todos', () => {
      return HttpResponse.json(null, { status: 500 })
    }),
  )

  // This override only applies to this test — resetHandlers() clears it
})
```

**Why MSW over mocking hooks:**

- Tests the full integration (fetch → parse → cache → render)
- Works across unit tests, integration tests, Storybook, and Cypress
- Network-level mocks survive refactors of hook internals

## Common Gotchas

### Retries cause slow/hanging tests

The default 3 retries with exponential backoff means a failing query takes ~6 seconds before the error surfaces. Always set `retry: false` on the test QueryClient.

If your production code sets retry directly on `useQuery`, it **cannot be overridden** by the test QueryClient. Use `queryClient.setQueryDefaults` instead:

```tsx
// In production setup — overridable in tests
queryClient.setQueryDefaults(['todos'], { retry: 5 })

// In test QueryClient — retry: false overrides the default
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})
```

### Assertions run before query resolves

Always wrap assertions in `waitFor`:

```tsx
// Don't — assertion runs before fetch completes
expect(result.current.data).toHaveLength(3)

// Do
await waitFor(() => {
  expect(result.current.data).toHaveLength(3)
})
```

### Stale cache between tests

If tests share a `QueryClient`, cached data from test A leaks into test B. Create a new wrapper (and thus a new `QueryClient`) for every test.

### Testing error boundaries

When testing components that use `throwOnError`, wrap the test render in an error boundary:

```tsx
import { ErrorBoundary } from 'react-error-boundary'

test('renders error boundary on server error', async () => {
  server.use(
    http.get('/api/todos', () => HttpResponse.json(null, { status: 500 })),
  )

  render(
    <ErrorBoundary fallback={<div>Something went wrong</div>}>
      <TodoList />
    </ErrorBoundary>,
    { wrapper: createWrapper() },
  )

  await waitFor(() => {
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
```
