# Optimistic Updates

- [When to Use Optimistic Updates](#when-to-use-optimistic-updates)
- [Full Optimistic Update Pattern](#full-optimistic-update-pattern)
- [Direct Cache Updates (Without Optimism)](#direct-cache-updates-without-optimism)
- [Concurrent Optimistic Updates](#concurrent-optimistic-updates)
- [List vs Detail Cache Updates](#list-vs-detail-cache-updates)

## When to Use Optimistic Updates

Use optimistic updates **only** when:

- The operation **rarely fails** (toggling a like, marking as read)
- **Instant feedback** is essential for UX
- The client can **predict the server result** without complex logic

**Do not use** when:

- The operation involves complex server logic (ID generation, computed fields, sorting)
- The component navigates away or closes on success (rollback is invisible)
- The operation is unreliable or network-dependent
- Simple invalidation with a loading indicator provides acceptable UX

Default to invalidation (low complexity). Reach for optimistic updates only when the UX benefit justifies the rollback complexity.

## Full Optimistic Update Pattern

The standard lifecycle: cancel in-flight queries, snapshot previous data, apply optimistic update, rollback on error, invalidate on settle.

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'

export function useToggleTodo() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (todo: Todo) =>
      updateTodo({ ...todo, done: !todo.done }),

    onMutate: async (todo) => {
      // 1. Cancel in-flight queries so they don't overwrite our optimistic update
      await queryClient.cancelQueries({ queryKey: todoKeys.detail(todo.id).queryKey })

      // 2. Snapshot previous value for rollback
      const previous = queryClient.getQueryData(todoKeys.detail(todo.id).queryKey)

      // 3. Apply optimistic update
      queryClient.setQueryData(
        todoKeys.detail(todo.id).queryKey,
        (old: Todo) => ({ ...old, done: !old.done }),
      )

      // 4. Return snapshot as context for rollback
      return { previous }
    },

    onError: (_err, todo, context) => {
      // 5. Rollback on error
      if (context?.previous) {
        queryClient.setQueryData(todoKeys.detail(todo.id).queryKey, context.previous)
      }
    },

    onSettled: (_data, _err, todo) => {
      // 6. Always invalidate to sync with server truth
      queryClient.invalidateQueries({ queryKey: todoKeys.detail(todo.id).queryKey })
    },
  })
}
```

**Key points:**

- `cancelQueries` prevents a pending fetch response from overwriting the optimistic update.
- The `context` object returned from `onMutate` carries the snapshot through to `onError`.
- `onSettled` fires on both success and error — always invalidate to sync with server.

## Direct Cache Updates (Without Optimism)

When the mutation response returns the full updated entity, update the cache directly without optimistic prediction:

```tsx
export function useUpdateTodo() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (todo: TodoUpdate) =>
      axios.patch<Todo>(`/todos/${todo.id}`, todo).then((r) => r.data),

    onSuccess: (updatedTodo) => {
      // Server returned the full entity — put it directly in cache
      queryClient.setQueryData(
        todoKeys.detail(updatedTodo.id).queryKey,
        updatedTodo,
      )

      // Invalidate lists to refetch with updated item
      queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
    },
  })
}
```

This is simpler than optimistic updates — no rollback needed since you're using the actual server response. Use this when:

- The API returns the full updated entity
- A brief loading state is acceptable
- You want to skip a full list refetch for the detail view

## Concurrent Optimistic Updates

When multiple mutations can target the same data simultaneously (e.g., rapid toggling, bulk actions), the default pattern breaks — `onSettled` invalidation from the first mutation overwrites the second mutation's optimistic state.

**Guard invalidation with `isMutating`:**

```tsx
export function useToggleTodo() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: ['toggleTodo'],
    mutationFn: toggleTodo,

    onMutate: async (todo) => {
      await queryClient.cancelQueries({ queryKey: todoKeys.detail(todo.id).queryKey })
      const previous = queryClient.getQueryData(todoKeys.detail(todo.id).queryKey)

      queryClient.setQueryData(
        todoKeys.detail(todo.id).queryKey,
        (old: Todo) => ({ ...old, done: !old.done }),
      )

      return { previous }
    },

    onError: (_err, todo, context) => {
      if (context?.previous) {
        queryClient.setQueryData(todoKeys.detail(todo.id).queryKey, context.previous)
      }
    },

    onSettled: () => {
      // Only invalidate when this is the last in-flight mutation
      if (queryClient.isMutating({ mutationKey: ['toggleTodo'] }) === 1) {
        queryClient.invalidateQueries({ queryKey: todoKeys.all })
      }
    },
  })
}
```

**Why `=== 1`?** In `onSettled`, the current mutation is still counted. A value of `1` means "I am the last one settling."

Use `mutationKey` to scope the `isMutating` check. Without it, unrelated mutations could prevent invalidation.

## List vs Detail Cache Updates

When updating a single item, you often need to update both the detail cache and the list cache.

### Update detail + invalidate list

The simplest approach — update the detail cache directly, invalidate lists to refetch:

```tsx
onSuccess: (updatedTodo) => {
  queryClient.setQueryData(todoKeys.detail(updatedTodo.id).queryKey, updatedTodo)
  queryClient.invalidateQueries({ queryKey: todoKeys.lists() })
},
```

### Update both caches optimistically

For full optimistic UI across list and detail views:

```tsx
onMutate: async (todo) => {
  await queryClient.cancelQueries({ queryKey: todoKeys.all })

  const previousDetail = queryClient.getQueryData(todoKeys.detail(todo.id).queryKey)
  const previousList = queryClient.getQueryData(todoKeys.list(currentFilters).queryKey)

  // Update detail cache
  queryClient.setQueryData(
    todoKeys.detail(todo.id).queryKey,
    (old: Todo) => ({ ...old, done: !old.done }),
  )

  // Update list cache
  queryClient.setQueryData(
    todoKeys.list(currentFilters).queryKey,
    (old: Todo[]) =>
      old.map((t) => (t.id === todo.id ? { ...t, done: !t.done } : t)),
  )

  return { previousDetail, previousList }
},

onError: (_err, todo, context) => {
  if (context?.previousDetail) {
    queryClient.setQueryData(todoKeys.detail(todo.id).queryKey, context.previousDetail)
  }
  if (context?.previousList) {
    queryClient.setQueryData(todoKeys.list(currentFilters).queryKey, context.previousList)
  }
},
```

**Complexity warning:** Updating list caches optimistically requires knowing which list queries are active and how the update affects filtering/sorting. In most cases, updating the detail cache + invalidating lists is the better trade-off.
