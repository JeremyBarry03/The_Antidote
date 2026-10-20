# Code Guidelines

These guidelines are a loose baseline for writing maintainable code in this
repo. They are not meant to be overly strict or slow down your work. When in
doubt, prefer code that is clear, consistent with nearby files, easy to test,
and easy for another developer to change later.


## Object-Oriented Design

Use OOP to create clear boundaries, maintainability and ease of development. 

- Give each class one clear responsibility and one main reason to change.
- Avoid deep inheritance trees, where possible. They usually make behavior harder to track and debugging complex.
- Favor Composotion Over Inheritance When Possible.
- Put shared behavior in well-named base classes or focused mixins.
- Keep constructors simple. Heavy setup, I/O, model loading, or network calls
  should usually live in factories or explicit setup methods.
- Use [software design patterns](https://refactoring.guru/design-patterns) when they solve a concrete problem; prefer
  familiar patterns such as factories, builders, strategies, or adapters over
  custom abstractions.

This example shows the common defense contract: each strategy returns a `DefenseResult`, and every concrete defense has to implement the same `apply` method so runner code can call defenses uniformly.

```python
@dataclass
class DefenseResult:
    frame: np.ndarray
    frame_kind: str
    attack_detected: Optional[bool] = None


class DefenseStrategy(Strategy):
    supports_tracking: bool = False

    @abc.abstractmethod
    def apply(
        self,
        frames: List[np.ndarray],
        defense_enabled_flags: List[bool],
    ) -> List[DefenseResult]:
        """Apply the defense to a batch of frames."""
```

This factory example keeps construction logic out of callers. Callers provide a strategy model, and the factory resolves the registered implementation or raises a useful error if the model is misconfigured.

```python
class DefenseStrategyFactory:
    """Maps a defense model's strategy_type to its strategy class."""

    @staticmethod
    def create(strategy_model) -> "DefenseStrategy":

        cls = DEFENSE_STRATEGY_REGISTRY.get(strategy_model.strategy_type)
        if not cls:
            raise ValueError(
                f"Unknown defense strategy_type: {strategy_model.strategy_type}. "
                f"Registered types: {list(DEFENSE_STRATEGY_REGISTRY.keys())}"
            )
        return cls(strategy_model=strategy_model)
```

### Mixins

- Prefer mixins for reusable, composable capabilities shared across related
  classes, as in WatchTower strategy and runner code.
- Keep mixins focused on one capability, name them with a `Mixin` suffix.
- Use constrained mixin bases when a mixin only makes sense for a specific
  domain, such as attack, defense, strategy, or runner classes.

This mixin collects the shared state and requirements for GPU-batch perturbation style attacks. The class name, inherited capabilities, and explicit attributes make the consuming strategy contract visible instead of hiding it in scattered helpers.

```python
class BatchPerturbationMixin(
    PerturbationCacheMixin,
    LiveParameterUpdatingMixin,
    AttackStrategy,
):
    """Base for GPU-batch attacks with two-level perturbation caching."""

    nw_strategy_class = None
    cache_iterations_param = "max_iter"

    needs_wrapped_model = True
    needs_names_map = True
```


### Abstraction

Abstractions should make code easier to change, not add complex overhead.

- Introduce an abstraction when it removes duplication, hides an unstable
  dependency, clarifies a domain concept, or supports multiple implementations.
- Prefer simple functions for pure transformations and small utilities.
- Avoid catch-all helper modules. Group helpers around a specific concept.

This helper is a small abstraction around protocol detection. It gives repeated URL parsing rules one name and one place to change.
```python
def infer_stream_protocol(stream_url: str) -> Optional[str]:
    """Infer a stream protocol label from a source URL."""
    lowered = (stream_url or "").strip().lower()
    if lowered.startswith(("rtsp://", "rtsps://")):
        return "RTSP"
    if lowered.startswith(("rtmp://", "rtmps://")):
        return "RTMP"
    if lowered.startswith("srt://"):
        return "SRT"
    if lowered.endswith(".m3u8") or ".m3u8?" in lowered:
        return "HLS"
    if lowered.endswith(".mpd") or ".mpd?" in lowered:
        return "MPEG_DASH"
    if lowered.startswith(("http://", "https://")):
        return "HTTP"
    return None
```

## General Clean Code Principles

- Prefer simple control flow. Use guard clauses to reduce nesting, split complex
  branching into named helpers when it improves readability, and make the happy
  path easy to follow.
- Keep function signatures clear. Avoid long parameter lists, group related
  values into typed objects or config classes, and avoid boolean flags that
  make one function handle unrelated behaviors.  This is harder with some of our data science work, but use your best judgement.
- Avoid magic values. Give names to repeated numbers, strings, timeouts, limits,
  feature flags, and status values. Make units explicit in names, such as
  `timeout_seconds` or `max_retries`.
- Prefer immutability where practical. Prefer to treat inputs as read-only unless mutation
  is the purpose of the function.

This `apply` method starts with a guard clause before doing heavier work, which keeps the happy path flatter and easier to follow.

```python
def apply(
    self,
    frames: List[np.ndarray],
    attack_enabled_flags: List[bool],
    frame_indices: Optional[List[int]] = None,
    detections_list: Optional[List] = None,
) -> List[Tuple[np.ndarray, str]]:
    if not frames:
        return []
```

This function returns a consistent tuple.

```python
def _resolve_targeting(
    self,
    original_w: int,
    original_h: int,
    batch_tensor: torch.Tensor,
) -> Tuple[Optional[OverlayAttackType], Optional[int], Optional[torch.Tensor]]:

  ...

    return overlay_attack_type, target_cls_id, regional_xyxy_bbox
```

## File Organization

- Group files by related responsibility and domain concept. A developer should
  be able to scan a directory and understand what kind of code belongs there.
- Avoid dumping unrelated code into broad folders such as `utils`, `core`,
  `helpers`, or `misc`. If a helper only supports one feature area, keep it
  near that feature instead of making it globally shared.
- Put experimental and exploratory work in a clearly marked area away from production grade code, like the `/experiments` folder.
- Avoid duplicate concepts in multiple places. If two folders appear to own a similar responsibility, consolidate around the concept before adding more files.
- Before adding a new folder, check whether an existing directory already owns
  that responsibility. Before adding a new file to a large directory, consider
  whether a focused subdirectory would make future changes easier to find.

This layout example shows related backend concepts grouped by responsibility: service orchestration, strategy implementations, stream utilities, and tests live in predictable places.

```text
./WatchTowerBackend/
  services/
    input_stream.py
    run_manager.py
    strategy_lookup.py
  strategies/
    attacks/
    defenses/
    mixins/
  stream/
    ffmpeg.py
    pts_tracker.py
    playlist_postprocessor.py
  tests/
    services/
    strategies/
    stream/
```

## Naming Conventions

Names should describe intent and domain meaning.

- Avoid vague names like `data`, `obj`, `manager`, or `handler` unless the scope is very small or the meaning is obvious.
- Use descriptive test names such as `test_returns_error_when_model_is_missing`.


### Python

- Use `snake_case` for modules, functions, variables, and methods.
- Use `PascalCase` for classes.
- Use `UPPER_SNAKE_CASE` for constants.
- Prefix private helpers with `_` when they are not part of the module's public
  API.


### TypeScript and React

- Use `PascalCase` for components, contexts, classes, interfaces, and type
  aliases.
- Use `camelCase` for functions, variables, props, and local helpers.
- Use `UPPER_SNAKE_CASE` for true constants.
- Prefix custom hooks with `use`.


## Typing Standards

Use types to document contracts and catch mistakes early.

### Python

- Add type hints to public functions, methods, service boundaries, and shared
  utilities.
- Use precise types where reasonable. Avoid `Any` as much as possible.
- Use enums or literal values for repeated status/type fields instead of loose
  strings.
- Keep return types consistent. Do not return multiple unrelated shapes from the
  same function unless the type makes that explicit.

This service signature documents a stable return shape with optionals. Callers can consistently unpack `(format, url, error)` instead of handling several unrelated response shapes.

```python
def configure_reupload_output(
    payload,
    run_instance,
    run_type: str,
) -> Tuple[Optional[str], Optional[str], Optional[JsonResponse]]:
    if not reupload:
        return None, None, None

    return reupload_format, reupload_output_url, None
```

This enum replaces loose protocol strings with named values, which makes validation and comparisons less error-prone across services and config code.

```python
class ReuploadFormat(str, Enum):
    RTSP = "RTSP"
    RTMP = "RTMP"
    HLS = "HLS"
    SRT = "SRT"
    WEBRTC = "WEBRTC"
    MPEG_DASH = "MPEG_DASH"
```

### TypeScript

- Keep TypeScript strict and strongly typed.
- Avoid `any` as much as possible, and use strong typing where applicable.
- Define API response/request types and reuse them across components, hooks, and
  helpers.
- Type component props explicitly.

This props interface makes component inputs explicit. It captures the allowed status and sort values at the boundary where the UI component receives them.

```tsx
interface RunFiltersProps {
    statusFilter: "all" | "PENDING" | "RUNNING" | "FAILED" | "DONE" | "STOPPED";
    sortBy: string;
    sortOrder: "asc" | "desc";
    onStatusFilterChange: (
        value: "all" | "PENDING" | "RUNNING" | "FAILED" | "DONE" | "STOPPED",
    ) => void;
    onSortByChange: (value: string) => void;
    onSortOrderChange: (value: "asc" | "desc") => void;
    onClearFilters: () => void;
}
```

This frontend enum centralizes run statuses so components compare against shared values instead of duplicating status strings throughout the app.

```ts
export enum RunStatus {
    PENDING = "PENDING",
    RUNNING = "RUNNING",
    STOPPING = "STOPPING",
    FAILED = "FAILED",
    DONE = "DONE",
    STOPPED = "STOPPED",
}
```

## Error Handling

- Fail early when required inputs are missing or invalid.
- Raise or return errors that explain what failed and what value/state caused it. Explained errors help debugging down the line.
- Catch specific exceptions whenever possible.

This view code fails before creating a run when the request method, active run state, or required attack id is invalid, giving the client specific messages at the boundary.

```python
if request.method != "POST":
    return JsonResponse({"error": "Method not allowed"}, status=405)

if RunManager.is_busy():
    return JsonResponse({"error": "A run is already processing"}, status=400)

attack_id = payload.get("attack_id")
if not attack_id:
    return JsonResponse(
        {
            "error": (
                "An attack strategy is required for attack runs. "
                "Use /api/start-passthrough-run/ for no-strategy runs."
            )
        },
        status=400,
    )
```


## Testing Standards

Tests should protect behavior, not implementation details.

- Add tests for new behavior, bug fixes, and refactors.
- Use small, focused tests that attempt to test only a specific case.
- Mock external systems such as network calls, subprocesses, storage, Redis,
  model downloads, browsers, and GPU-heavy work.
- Do not mock simple value objects or pure helpers unless there is a valid
  reason.
- Include failure cases, edge cases, and validation behavior.
- For data science code, test as much deterministic behavior where possible.

This backend test focuses on observable behavior: when attacks are disabled, the original frames are returned and marked `NOMINAL`.

```python
def test_apply_returns_nominal_when_no_frames_enabled(self):
    frames = [
        np.zeros((3, 3, 3), dtype=np.uint8),
        np.ones((3, 3, 3), dtype=np.uint8),
    ]
    result = self.strategy.apply(frames, [False, False])
    self.assertEqual(len(result), 2)
    self.assertTrue(np.array_equal(result[0][0], frames[0]))
    self.assertEqual(result[0][1], FrameKind.NOMINAL)
```

This route test mocks the API boundary and verifies the loader api contract, which protects the behavior React Router depends on without rendering the whole page.

```tsx
describe("clientLoader", () => {
    it("loads all runs successfully", async () => {
        const { runApi } = await import("~/lib/api");
        vi.mocked(runApi.getAll).mockResolvedValue(mockRuns as any);

        const result = await clientLoader({ params: {} } as any);

        expect(runApi.getAll).toHaveBeenCalled();
        expect(result).toEqual(mockRuns);
    });
});
```

## Formatting and Consistency

- Keep imports organized and remove unused imports.
- Keep files cohesive. If a file grows large because it owns multiple concepts,
  split it by responsibility.  If you have to scroll a lot to see different parts of a file, that's probably a good sign you should start to think to break things up.
- Keep comments useful. Explain non-obvious decisions, invariants, tradeoffs,
  and workarounds. Comments can be a crutch and cop-out for poorly written code.
- Avoid large blocks of commented-out code.
- Keep dependencies pinned for security reasons.


## Frontend Guidelines

- Keep components focused and reusable.
- Move API calls into API/helper modules rather than embedding request logic
  within components.
- Move repeated formatting, filtering, sorting, and form parsing into shared
  helpers with tests.
- Keep UI state local unless it must be shared.
- Use context sparingly for cross-cutting state, not as a default global store.
- Prefer controlled, typed props over implicit/"any" typing ESPECIALLY for things like API responses.
- With React Router, prefer using clientLoaders over useEffect and clientAction over "onSubmit" style functions.

This route uses a `clientLoader` for fetching initial video data and then reads it with `useLoaderData`, which keeps data loading aligned with React Router instead of hiding it in an effect.

```tsx
export async function clientLoader({ params }: Route.ClientLoaderArgs) {
    return await videoApi.getAll();
}

export default function Videos() {
    const data = useLoaderData<typeof clientLoader>();
    const revalidator = useRevalidator();
}
```

This API helper centralizes request logic and error translation for models, so components can call `modelApi.getAll` without embedding endpoint paths or axios handling.

```tsx
export const modelApi = {
    async getAll(filters?: ModelFilters): Promise<Model[]> {
        try {
            const response = await api.get<Model[]>(
                "/object_detection_models/",
                { params: filters },
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching models:", error);
            throw new Error("Failed to fetch models");
        }
    },
};
```

This modal prop type documents the controlled inputs and callback contract for uploads, making the component reusable without relying on implicit prop shapes.

```tsx
interface AddVideoModalProps {
    isOpen: boolean;
    onClose: () => void;
    isSubmitting?: boolean;
    error?: any;
    onUpload: (files: File[], kind: string, notes: string, name: string) => void;
}
```

## Backend Guidelines

- Keep request handlers thin and move reusable behavior into services or helpers.
- Validate incoming data before starting expensive or long-running work.
- Keep configuration, constants, and repeated string values centralized.
- Make background jobs and long-running processes easy to stop, retry, and debug.

This view snippet shows a thin handler delegating stream lookup and output video creation to services, leaving the request flow readable.

```python
input_video, stream_input_url, error = resolve_input_stream(
    payload,
    attack_run,
    "attack",
    record_live_stream=not recording_disabled,
)
if error:
    return error

output_video = create_output_video(input_video, Kind.ATTACKED, attack_run.name)
```

This config class centralizes URL constants and builders for stream endpoints, avoiding repeated host, port, and path strings in runners and views.

```python
class RTSPConfig:
    BASE_HOST = "localhost"
    BASE_PORT = 8554

    ATTACK_PATH_PREFIX = "/live/attack_"
    DEFENSE_PATH_PREFIX = "/live/defense_"
    PASSTHROUGH_PATH_PREFIX = "/live/passthrough_"

    @classmethod
    def get_attack_url(cls, run_id: str = "1") -> str:
        return f"{cls.get_base_url()}{cls.ATTACK_PATH_PREFIX}{run_id}"
```

This run manager owns background-run lifecycle state and stop signaling in one place, which makes long-running work easier to manage and modify.

```python
class RunManager:
    _lock = threading.Lock()
    _active_thread: threading.Thread = None
    _active_runner = None

    @classmethod
    def stop_run(cls, run_instance) -> None:
        if run_instance.status != Run.Status.RUNNING:
            raise ValueError(
                f"Cannot stop run with status {run_instance.status}. "
                f"Only RUNNING runs can be stopped."
            )

        client = get_redis_client()
        stop_key = RedisConfig.get_stop_signal_key(run_instance.id)
        client.set(stop_key, "true", ex=300)

        with cls._lock:
            if cls._active_runner is not None:
                cls._active_runner.request_stop()
```



## Code Preferences

A collection of small preferences you should expect to see in our
code. None of these are dealbreakers on their own, but together they keep the
codebase consistent and easier to maintain.

### Python

- **Prefer `pathlib.Path` over `os.path`.** Build paths with `Path(...) / "subdir" / "file.txt"`,
  not `os.path.join`. Use `path.exists()`, `path.read_text()`, `path.mkdir(parents=True, exist_ok=True)`
  instead of the `os` equivalents.

```python
from pathlib import Path

config_path = Path(__file__).parent / "config" / "defaults.yaml"
if not config_path.exists():
    raise FileNotFoundError(f"Missing config: {config_path}")
contents = config_path.read_text()
```

- **F-strings for formatting.** Use f-strings everywhere. Avoid `%`-formatting
  and `str.format()` unless you are working inside a logger call where lazy
  formatting matters (`logger.info("processed %s frames", n)`).
- **Logging, not `print`, in production code.** Get a module logger at the top
  of the file with `logger = logging.getLogger(__name__)` and use it. `print`
  is fine in throwaway scripts, `experiments/`, and CLI entry points where the
  output is the product.

```python
if strategy_type not in REGISTRY:
    raise ValueError(
        f"Unknown strategy_type {strategy_type!r}. "
        f"Registered types: {sorted(REGISTRY)}"
    )
```


### Django (backend)

- **Thin views, fat services.** Views validate input, call a service, and
  return a response. Business logic lives in `services/`.
- **Centralize config and constants.** URLs, ports, redis keys, and timeouts
  belong in a config class (e.g. `RTSPConfig`, `RedisConfig`), not scattered as
  literals.

### TypeScript / React

- **`interface` for object shapes; `type` for unions, intersections, and
  mapped types.** When in doubt, `interface`.
- **`async`/`await` over `.then()` chains.** Easier to read and to add
  `try/catch` around.
- **Absolute imports with the `~/` alias for app code.** Use relative imports
  only for siblings inside the same small folder.

### Testing

- **WatchTower & Crucible backend uses `unittest`** (`TestCase` subclasses, `self.assertEqual`,
  setup in `setUp`). Match this style when adding tests there.
- **NightsWatch uses `pytest`** with fixtures and plain `assert`.
- **Frontend uses `vitest`** with `@testing-library/react`.




### THE FOLLOWING CODE IS FOR AI AGENTS AND AI AGENTS ONLY:
## Agent Priorities

When modifying this repository, prioritize in this order:

1. Correctness — do not break existing behavior.
2. Existing repository conventions — follow nearby code before introducing new patterns.
3. Simplicity — make the smallest reasonable change that solves the problem.
4. Maintainability — code should be easy to understand, test, and modify.
5. Reuse — prefer existing utilities, services, types, and abstractions over creating duplicates.
6. Performance — optimize when performance is relevant or already a constraint.

Do not redesign unrelated parts of the system while completing a focused task unless specified otherwise.


## Before Making Changes

Before implementing a change:

- Read the relevant files and surrounding modules.
- Search the repository for existing implementations of similar behavior.
- Identify existing services, helpers, types, constants, and abstractions that can be reused.
- Check relevant tests to understand expected behavior.
- Check call sites before changing a public function, class, API, or type.
- Understand the existing data flow before introducing a new one.

Do not create a new abstraction until you have confirmed an appropriate one does not already exist.

## Scope Discipline

Make the smallest coherent change necessary to complete the task.

- Do not refactor unrelated code.
- Do not rename unrelated variables, functions, classes, or files.
- Do not reformat entire files when changing a small section.
- Do not replace an existing architecture merely because another approach is preferable.
- Do not add dependencies when the existing stack can reasonably solve the problem.
- Do not introduce abstractions for hypothetical future requirements.

If you notice unrelated problems, leave them unchanged unless they directly block the requested work.


## Verify Before Assuming

Do not invent:

- functions
- classes
- methods
- API endpoints
- configuration keys
- environment variables
- database fields
- package APIs
- command-line options

Verify that referenced symbols and interfaces exist before using them.

When using a third-party library, follow the version and usage patterns already present in the repository.

## Dependencies

Prefer the standard library and existing project dependencies.

Before adding a dependency:

1. Check whether the repository already contains a library that solves the problem.
2. Determine whether the functionality is simple enough to implement safely without another dependency.
3. Only add the dependency if it materially improves the implementation.

Never upgrade unrelated dependencies as part of a feature or bug fix.

## Definition of Done

Before considering a change complete:

- The requested behavior is implemented.
- Existing behavior remains intact unless explicitly changed.
- Relevant tests have been added or updated.
- Existing relevant tests pass.
- New code follows repository typing standards.
- Imports are valid and unused imports are removed.
- No debugging prints, temporary code, commented-out code, or placeholder TODOs remain.
- Public interfaces and call sites remain consistent.
- New configuration or environment requirements are documented.

## Database Changes

When modifying database-backed models:

- Prefer backward-compatible schema changes where practical.
- Create migrations for schema changes.
- Do not edit previously deployed migrations unless explicitly required.
- Avoid destructive migrations without a clear migration strategy.
- Consider existing rows when adding non-null fields.
- Keep database constraints aligned with application validation.
- Avoid N+1 queries and unnecessary repeated database access.
- Use transactions when multiple related writes must succeed or fail together.

## API Contracts

Treat existing API contracts as stable unless the task explicitly changes them.

When modifying an endpoint:

- Preserve response shapes unless a contract change is required.
- Preserve HTTP status semantics.
- Validate input at the boundary.
- Keep frontend and backend types synchronized.
- Consider existing callers before renaming or removing fields.
- Prefer additive changes over breaking changes.

## Security

- Never hard-code secrets, credentials, API keys, tokens, or passwords.
- Never log secrets, authentication tokens, or sensitive payloads.
- Treat all external input as untrusted.
- Validate and sanitize input at system boundaries.
- Use parameterized queries / ORM APIs rather than constructing queries from user input.
- Preserve authentication and authorization checks when modifying endpoints.
- Do not weaken security controls to make development easier.
- Keep sensitive configuration in environment variables or the repository's existing secret-management system.

## Machine Learning / Data Science

- Make randomness deterministic when practical by setting explicit seeds.
- Keep model configuration separate from execution logic.
- Avoid hard-coded device assumptions; handle CPU/GPU selection explicitly.
- Use `torch.no_grad()` / inference modes where gradients are unnecessary.
- Avoid unnecessary device transfers between CPU and GPU.
- Batch operations where practical instead of processing samples individually.
- Preserve tensor shape, dtype, and device expectations at function boundaries.
- Document non-obvious tensor dimensions.
- Validate model inputs before expensive inference.
- Do not silently resize, normalize, cast, or otherwise transform model inputs unless that behavior is part of the defined pipeline.
- Keep training/evaluation/inference behavior clearly separated.
- Record or expose parameters necessary to reproduce experiments.

## Performance

Do not optimize prematurely, but avoid obviously expensive patterns.

Be particularly careful with:

- per-frame work in video pipelines
- repeated model loading
- repeated network/database calls inside loops
- unnecessary tensor copies
- CPU/GPU transfers
- synchronous I/O in latency-sensitive paths
- loading entire large files/datasets when streaming is possible

Initialize expensive resources once when their lifetime allows it.

## Concurrency and Background Work

- Treat shared mutable state as unsafe unless access is synchronized.
- Do not introduce global mutable state without a clear lifecycle.
- Ensure background work has explicit start, stop, failure, and cleanup behavior.
- Use `try/finally` where cleanup must occur even after failures.
- Do not leave threads, subprocesses, sockets, streams, or GPU resources orphaned.
- Make stop operations idempotent where practical.
- Preserve existing locking and lifecycle guarantees when modifying concurrent code.

