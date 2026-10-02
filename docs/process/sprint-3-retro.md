# Sprint 3 retro

## What went well

Our AWS setup and wiring held up well. Because we tested early in Sprint 1 and had the CI/CD pipeline in place, infrastructure issues were quick to debug and didn't slow us down. We also sequenced our tasks up front, so everyone knew what depended on what and what to pick up next. By the time we implemented later features like `trace`, most of the system already existed, which made it clear where new code connected and kept merges smooth.

## What didn't go well

The Reviewer was our main source of bugs, especially in how it interacted with the rest of the graph. We also hit recurring bugs from data-shape mismatches between components, such as graph state, proposals and graph outputs. Finally, our scope wasn't clearly defined at the start of the project, and that ambiguity carried into this sprint.

## One concrete change for next sprint

Now that Sprint 2's debugging and testing have stabilized the workflow, we will front-load evaluation and tuning in Sprint 3.

