# Academic email categories: labelling guide (DRAFT)

Draft written by the AI from the learner's Phase 2 decisions. The categories
are the learner's design; edit these definitions and rules freely. They are
what every label in `dataset.json` is checked against.

The same 11 categories apply to both inbox roles (`student`, `instructor`).
The role changes the example emails and, later, the reply context. It never
changes which category an email belongs to.

## How to choose a label

Label by **what the newest message needs from the inbox owner**, not by its
topic. Ignore quoted earlier messages and signatures. If two categories fit,
use the first one that applies in this order:

1. `spam`
2. `wellbeing`
3. `request_exception`
4. `meeting_request`
5. `admin_action`
6. `course_logistics`
7. `academic_question`
8. `collaboration_opportunity`
9. `announcement_promo`
10. `informational`
11. `ambiguous` (only when none of the above clearly fits)

Distress or an exception request inside another kind of email outranks the
rest, because missing it is the costliest mistake.

## Categories

### `announcement_promo`
Bulk mail sent to many people: newsletters, event and seminar announcements,
club mail, LinkedIn/Handshake notifications, marketing, mass course-wide
announcements with nothing to do.
- Student: "Career fair next Thursday in the Student Centre"
- Instructor: "Faculty newsletter: research funding deadlines"
- Rule: if a mass email requires an action by a deadline (submit, register,
  pay), it is `admin_action`, not this.
- Rule: a mass email that offers an optional opportunity (calls for
  volunteers, supervisors, committee members, applicants) is this, not
  `collaboration_opportunity`. Only an opportunity offered to the owner
  personally, or a personal ask on top of a forwarded announcement, is
  `collaboration_opportunity`.

### `informational`
Personal or course-specific FYI with nothing to answer: acknowledgements,
confirmations, status updates, short thank-yous.
- Student: "Your grade for Assignment 2 has been posted"
- Instructor: "I submitted my assignment, just letting you know"
- Rule: a thank-you or FYI that also asks a question is not `informational`.

### `admin_action`
Administrative task the owner must do, usually with a deadline. Needs action,
not a reply.
- Student: "Submit your OSAP documents by Friday", "Housing deposit due"
- Instructor: "Final grades are due in the portal by Dec 20", room booking
  confirmations to complete

### `course_logistics`
Questions or requests about how a course runs: dates, deadlines, rooms,
format, policies, grading scheme, submission rules, presentation slots.
- Student: TA asks "Please confirm your presentation slot"
- Instructor: "When is the midterm?", "Is the late penalty 10% per day?"
- Rule: asking for an exception to a policy is `request_exception`.

### `academic_question`
Questions about course content or understanding: concepts, assignment
problems, readings, feedback on work.
- Student: classmate asks "How did you approach Q3?"
- Instructor: "I don't understand part b of the assignment"

### `meeting_request`
Asks to meet, call, or book office hours, or to reschedule a meeting.
- Student: supervisor asks "Can we meet this week?", group meeting time
- Instructor: office-hours or appointment request
- Rule: a group-project email whose main ask is a meeting time is here.

### `request_exception`
Asks for something outside the normal rules, or follows up on one:
extensions, regrades, accommodations, missed-exam deferrals, late
submissions, documentation for an exception.
- Student: prof asks "Please send documentation for your extension"
- Instructor: extension, regrade, or accommodation request

### `collaboration_opportunity`
Group-project coordination (other than scheduling), research or lab
opportunities, RA/TA positions, co-authorship, joining a team.
- Student: RA position offer, lab invitation, group-task split
- Instructor: student asking to join a lab, research collaboration

### `wellbeing`
Distress, personal hardship, health, grief, or a request for support. Takes
priority over every other non-spam category when present.
- Student: stressed classmate, personal hardship
- Instructor: a student in distress
- Rule: "I'm sick, can I get an extension?" is `wellbeing` only if distress
  or hardship is the main content; a routine medical extension request is
  `request_exception`.

### `ambiguous`
Unclear what is being asked, or too little context to act on.
- "Following up on my email from last week", "Quick question" with no body

### `spam`
Phishing and scams: fake account suspensions, mailbox-full warnings, fake job
offers, prize and payment scams.
- Rule: a real university security or IT notice is `admin_action` or
  `informational`, not `spam`. The system will handle suspected phishing
  conservatively, so label what the email really is.
