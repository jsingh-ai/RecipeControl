import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => cleanup())

class ResizeObserverMock { observe() {}; unobserve() {}; disconnect() {} }
vi.stubGlobal('ResizeObserver', ResizeObserverMock)

vi.mock('echarts', () => ({
  init: () => ({
    setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn(), containPixel: () => true,
    convertFromPixel: () => Date.parse('2026-06-11T20:00:00Z'), dispatchAction: vi.fn(),
    getZr: () => ({ on: vi.fn(), off: vi.fn() }),
  }),
  graphic: { clipRectByRect: (shape: unknown) => shape },
}))
