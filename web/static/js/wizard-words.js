// One vocabulary for the three wizards.
//
// An operator uses 01, 02 and 03 in the same shift. If the same act is called
// "从头开始" on one page, "重新开始这颗电机" on the next and nothing at all on the
// third, they have to relearn the page instead of doing the job. The rule is: the
// same act reads the same everywhere, and the noun that differs is the only thing
// that differs.

/** The panel above a failure. Always the same two words, whatever went wrong. */
export const PROBLEM_KICKER = '需要处理';

/** The heading above the numbered fix steps. */
export const FIX_HEADING = '怎么解决';

/** The button that retries the step that just failed. */
export const RETRY = '处理好了，再试一次';

/**
 * Start this unit of work over. The noun is what the page is working on - 一条链路,
 * 这颗电机, 这台机械臂 - and nothing else about the wording changes.
 */
export function restartLabel(subject) {
    return `重新开始${subject}`;
}

/** Run a step that already completed, again. */
export const REDO_STEP = '重新测这一步';

/** Go back one step without losing what is done. */
export const BACK = '返回上一步';
