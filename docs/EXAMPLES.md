# Examples

This page shows the intended Life OS flow from natural language to structured records and plots.

## Daily Log

Input:

```text
Today I slept 6h, woke up tired, energy 5/10 and stress 7/10.
Ate oatmeal with dates, peanut butter, and chocolate in the morning.
Lunch was 180g cooked chicken with rice and salad.
Did lower body: squats 4x5 at 80%, RDL 3x8, and 12 min metcon.
Worked 3 hours on the global TAGI-LSTM paper and fixed the SKF motivation section.
Mood was okay but I felt mentally drained.
```

Stored first:

```text
raw_messages
- source: telegram
- user_text: original message exactly as sent
- processed: true
```

Then extracted into structured records:

```text
daily_checkins
- sleep_hours: 6
- energy: 5
- stress: 7
- notes: woke up tired and felt mentally drained

nutrition_logs
- breakfast: oatmeal with dates, peanut butter, and chocolate
- lunch: 180g cooked chicken with rice and salad

workout_logs
- type: lower body

workout_exercises
- squat: 4x5 at 80%
- Romanian deadlift: 3x8
- metcon: 12 min

career_logs
- project: global TAGI-LSTM paper
- duration_hours: 3
- progress_note: fixed the SKF motivation section

journal_entries
- text: Mood was okay but I felt mentally drained.
- tags: fatigue, stress, research
```

## Flexible Structured Logging

Equivalent workout phrasings should produce the same exercise record:

```text
I did squats 3 sets of 10 reps 100 kg.
I did 3sets 10 each squats with a 100 kg.
```

Both become:

```text
workout_exercises
- name: squat
- sets: 3
- reps: 10
- load: 100 kg
```

If an exercise is logged without sets, reps, or load, Life OS looks for the most recent matching exercise and fills only the missing fields. If there is no history, the fields stay empty.

Duplicate same-day structured rows are skipped. The raw message is still preserved, but Life OS avoids creating repeated workout, meal, career, wellbeing, or journal records when the same thing is sent twice.

For nutrition, explicitly provided calories are preferred. If calories are missing, Life OS may estimate a normal portion conservatively and ask whether you want to replace the estimate with actual calories.

## Deleting Logs

From Telegram:

```text
delete logs
delete meal #12
delete workout #4
delete last log
delete today's journal
```

`delete logs` lists recent candidates with IDs. Deleting a raw log removes the raw message and its structured children. Deleting a single structured record, such as a meal or workout, leaves the original raw message intact.

## Telegram Plot Commands

Single plot:

```text
plot my energy
```

Batch plot request:

```text
plot my energy
show my career hours
plot my workouts
plot protein for the last week
```

Life OS sends a separate image for each line. Plot requests are not stored as daily logs.

Supported commands include:

```text
plot my energy
plot sleep vs energy
show stress vs workouts
plot my workouts
show workout frequency
plot squat history
show my career hours
plot deep work by project
plot protein for the last week
show protein consistency
plot calories
show habit heatmap
```

## Example Plot

![Energy and stress example](assets/life-os-energy-stress.png)

## Design Notes

The chart style is intentionally restrained:

- off-white paper background
- black structure
- red accent for contrast
- direct labels instead of noisy legends where possible
- large titles and sparse grid lines

The goal is to make personal data feel calm, legible, and useful rather than dashboard-heavy.

## Personal Memory

Explicit memory commands are not stored as daily logs. They update durable preferences:

```text
remember that briefings should be direct and concise
remember that training early works for me
remember that I don't like vague motivational advice
```

Life OS stores these as structured memory:

```text
memory_items
- briefing_style: direct and concise
- strategy: training early
- aversion: vague motivational advice
```

Morning briefings receive both analytics and relevant memory. The model can adapt tone and recommendations without receiving arbitrary database access.
