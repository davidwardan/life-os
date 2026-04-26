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
