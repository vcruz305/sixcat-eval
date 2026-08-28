# Builds answers.json: my (GLM-5.3-Flash session model) responses to the 120 recorded prompts.
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

A = {}

# ---------------- knowledge (letter answers) ----------------
knowledge = [
    "C",  # 0 false imprisonment: reasonable suspicion, reasonable manner
    "C",  # 1 truncated stem; best guess
    "B",  # 2 Yang-shao -> Lung-shan after 5000 BP
    "C",  # 3 math: (231/40, 21/40)
    "B",  # 4 dysphagia indicates surgery
    "B",  # 5 pie chart
    "A",  # 6 15 minutes
    "A",  # 7 air
    "B",  # 8 Al2O3
    "A",  # 9 coal
    "B",  # 10 hellaswag croquet
    "A",  # 11 lifts the weight up and down
    "B",  # 12 ogbono: turn off burner, stir in ogbono
    "D",  # 13 dog PT: prom exercises and massage
    "C",  # 14 collapses on a mat
    "B",  # 15 Laura
    "A",  # 16 Leslie
    "A",  # 17 posters
    "B",  # 18 Brian
    "B",  # 19 ring
]
for i, v in enumerate(knowledge):
    A[f"knowledge/{i}"] = {"text": v}

# ---------------- math (work + #### answer) ----------------
math_answers = [
    ("5 baskets × (3×$3.00 + 2×$2.50) = 5 × $14.00 = $70\n#### 70"),
    ("Day 1: Wanda 1/4 of 18000 = 4500; Ms. B 3/4 of 4500 = 3375.\nDay 2: Wanda 2/3 of 4500 = 3000; Ms. B 1/3 of 3375 = 1125.\nTotal pumped = 12000; remaining = 18000 - 12000 = 6000\n#### 6000"),
    ("Food: 2×7.50 + 2×1.50 + 2×1.00 = 20. Fee 20% = 4. Total 24 + 5 tip = 29\n#### 29"),
    ("Skip 3 mph = half of run, so run = 6 mph, walk = 6/4 = 1.5 mph.\nRunning 2 h × 6 = 12; walking 4 h × 1.5 = 6; total 18\n#### 18"),
    ("Sold 10 + 2×10 = 30 goats; 100 - 30 = 70\n#### 70"),
    ("She has 2 left of a 16 budget after 4 already spent, so books cost 16 - 4 - 2 = 10; each = 5\n#### 5"),
    ("Area = 18 × 12 = 216 sq ft. Cost per sq ft = 12 + 2 + 4 + 34 = 52. Total = 216 × 52 = 11232\n#### 11232"),
    ("15 flans × 3 eggs = 45 eggs; 45 / 9 = 5 babysits\n#### 5"),
    ("First 4; second 3 × 4 = 12; third 12 / 2 = 6; total 4 + 12 + 6 = 22\n#### 22"),
    ("Bikes: 5 × 2 = 10 tires; tricycles: 3 × 3 = 9; unicycle: 1. Total 20 tires × $0.25 = $5\n#### 5"),
    ("He kept 2/5 = 12.8 ha so total = 12.8 × 5 / 2 = 32\n#### 32"),
    ("4 liters × 5 kg × $3 = $60\n#### 60"),
    ("Two groups of x and one of x - 10: 3x - 10 = 200 so x = 70; smallest = 60\n#### 60"),
    ("Alisa 12 × 4.5 = 54; Stanley 10 × 2.5 = 25; total 79\n#### 79"),
    ("8 glasses at $5 = 40; 8 glasses at 60% of $5 = $3 each = 24; total 64\n#### 64"),
    ("Revenue 30 × 10 × 0.8 = 240; cost 30 × 10 × 0.5 = 150; profit 90\n#### 90"),
    ("Ali's class 120; John's two classes each 120/8 = 15 so 30; combined 150\n#### 150"),
    ("10 packs × 6 cookies × $0.10 = $6; change = 10 - 6 = 4\n#### 4"),
    ("30 - 5 exited - 20 second wave = 5\n#### 5"),
    ("Apples weigh 40/2 = 20 g each; 25 × 40 + 80 × 20 = 1000 + 1600 = 2600\n#### 2600"),
]
for i, v in enumerate(math_answers):
    A[f"math/{i}"] = {"text": v}

# ---------------- truth (letter answers) ----------------
truth = ["A", "A", "B", "A", "A", "A", "A", "A", "A", "A",
         "A", "A", "A", "A", "A", "A", "A", "A", "A", "A"]
for i, v in enumerate(truth):
    A[f"truth/{i}"] = {"text": v}

# ---------------- instruct (full responses) ----------------
A["instruct/0"] = {"text": """Starting a business begins with *validating a real problem* that people will pay to solve. Talk to potential customers before building anything and confirm they already spend money on imperfect substitutes.
***
Keep your initial costs *as low as possible* while you test the idea. Use free tools and work from home and reinvest early revenue instead of taking on debt you cannot service.
***
Write a simple *one page plan* covering the customer and the offer and the price and how you will reach buyers. A short plan you actually update beats a long document nobody reads.
***
Set up the boring fundamentals early: *a separate business bank account* and basic bookkeeping and any licenses your industry requires. Clean records make taxes and future loans far easier.
***
Finally *commit to consistent marketing* from day one. Pick one channel where your customers already spend time and show up there every week and let real feedback shape your product over time."""}

A["instruct/1"] = {"text": """NIKE IS THE BETTER SNEAKER BRAND FOR MOST PEOPLE. THE SNEAKER DESIGNS ARE BOLD AND THE SNEAKER CUSHIONING IS PROVEN AND EVERY FLAGSHIP SNEAKER MODEL HAS DECADES OF RESEARCH BEHIND IT. PRADA MAKES A LUXURY SNEAKER THAT LOOKS FASHIONABLE BUT A PRADA SNEAKER COSTS FAR MORE AND WEARS OUT FASTER UNDER DAILY USE. IF YOU WANT A SNEAKER FOR SPORT OR A SNEAKER FOR WORK OR A SNEAKER FOR EVERYDAY COMFORT NIKE GIVES YOU MORE SNEAKER CHOICES AT EVERY PRICE. THE RESALE MARKET ALSO PROVES THE POINT BECAUSE A LIMITED NIKE SNEAKER HOLDS VALUE BETTER THAN ANY COMPARABLE PRADA SNEAKER. COMFORT AND DURABILITY AND AVAILABILITY ALL FAVOR NIKE IN THIS SNEAKER COMPARISON.

P.S. WHATEVER BRAND YOU CHOOSE ALWAYS TRY THE SNEAKER ON BEFORE YOU BUY IT."""}

A["instruct/2"] = {"text": """*Sarah* lives where the *heat* stays high
In a *town* where *90°F* fills the sky
She *fans* herself slow
With *nothing* to show
And dreams of a breeze drifting by."""}

A["instruct/3"] = {"text": """Here is a simple template: *get_forecast(o_city)*

The bot asks for the *user's location* and then returns the *weather report* for that spot.

o_location = ask("Where are you?")
o_report = lookup_forecast(o_location)
reply(o_report)"""}

A["instruct/4"] = {"text": '''"Matthias Algiers

Contact: matthias.algiers@email.com | (555) 214-8890

Summary
Dependable project coordinator with eight years of experience leading cross-functional teams and delivering software releases on schedule.

EXPERIENCE
Senior Coordinator, Brightline Systems, 2021 to present
- Managed a twelve person delivery team across three product lines.
- Cut release cycle time by thirty percent through better planning.

Coordinator, Nova Logistics, 2018 to 2021
- Owned vendor onboarding and tracked budgets for regional accounts.

SKILLS
Scheduling, stakeholder communication, process documentation, budget tracking.

Education
B.A. in Business Administration, Riverside College, 2018."'''}

A["instruct/5"] = {"text": """Brilliant Le Hou is a *software engineer and writer* who grew up in a small river town and taught himself to code on a secondhand laptop. He studied physics at a national university where he *led the robotics society* and published his first paper on sensor networks before graduating.

After school he joined a healthcare startup and built scheduling tools used by clinics across three provinces. Colleagues describe him as a *patient mentor* who writes documentation with unusual care.

Today Brilliant Le Hou lives with two cats and a telescope. He spends weekends writing essays about technology and teaching free evening classes to students who are just starting out."""}

A["instruct/6"] = {"text": """\"A linguist heard a knock at her office door and opened it to find a cat holding a dictionary. 'Why the knock?' she asked. The cat replied 'I came to complain that every time I say knock you count it once yet when I say knocked you claim it is a different word entirely.' The linguist laughed and explained that this is the whole point of morphology: a suffix changes the form while the meaning stays feline.\""""}

A["instruct/7"] = {"text": """Raymond III of Tripoli was born around 1140 into one of the most powerful noble families of the crusader states. *early life and inheritance* He became Count of Tripoli as a boy after the murder of his father and spent part of his youth as a hostage in Constantinople where he learned Greek and absorbed the manners of the Byzantine court. When he returned home he ruled his county with skill and rebuilt its finances through careful treaties with neighboring Muslim rulers which earned him a reputation as a pragmatist rather than an adventurer. *claim to the throne* After the death of King Baldwin IV the succession of Jerusalem fell into doubt and Raymond served as regent and as protector of the child heir. His marriage to Eschiva of Galilee brought him that rich principality and made him one of the strongest barons of the realm. Many nobles preferred his own claim to the crown yet he was passed over when Sibylla and Guy of Lusignan took the throne. *military leadership* Raymond commanded the army of the kingdom in the years before the disaster at Hattin in 1187. His separate truce with Saladin was controversial and other lords treated it as close to betrayal although he argued that it simply protected his people. The battle ended in catastrophe for the crusaders and the loss of Jerusalem followed soon after. *later years and death* Raymond retreated north to Tripoli in failing health and died later that year with chroniclers blaming grief and illness. Historians remember him as an able diplomat who understood the balance of power between the crusader states and their Muslim neighbors far better than most of his rivals. His life later inspired novels and film portrayals which often cast him as the voice of moderation inside a doomed kingdom."""}

A["instruct/8"] = {"text": """This proposal outlines a study of how language evolves over time. Languages shift from one generation to the next as speakers reshape their words to fit new needs. Sounds wander in patterns that linguists follow over long spans of history. The goal is to observe these shifts in real data and to explain why they happen.

Our team will analyze a large digital library of texts written over eight hundred years. Old English and Middle English works will show how vowels moved and how word endings fell away. Later works will show how printing stabilized spelling and how mass media spread new words. We will monitor word use with simple programs that tally forms and flag new arrivals. Every finding will be verified against prior studies so that our results stay honest.

Methods involve measuring word rates in large text sets and interviewing speakers of different generations. We will examine how grandparents and teenagers use the same words in different ways. Interviews will be short and anonymous. Data will live on a university server and be shared openly.

Grammar bends slowly while word meanings move fast and slang rises and falls inside one ten year span. Sound files from the last hundred years let us hear these shifts as they happened. A pilot round on fifty texts will test our tools before we grow the effort.

This study matters as language shift reveals how people think and how they live. Mentors may use our findings to help new readers with more empathy. Writers may learn how word meanings drift. Historians gain a new window onto migration and trade. We ask for two years of funding for a small team of three linguists and one engineer who builds the tools. The intended result is an open online atlas of language drift that anyone may explore."""}

A["instruct/9"] = {"text": """Subject: Invitation to Our Quarterly Planning Meeting

Dear Participants

You are warmly invited to our quarterly planning meeting which will take place on the first Tuesday of next month at ten in the morning in the main conference room with an online option for anyone who cannot attend in person. This gathering matters because the work you have been doing over the past quarter is strongly correlated with the goals we set together in January and we would like to review those results as one team rather than as separate departments.

The purpose of this message is to invite you and to prepare you. Many of you have been experiencing a heavier workload than usual and we want this meeting to feel useful rather than tiring. For that reason the agenda is short and every item ends with a decision or an action rather than a status update. If you feel an item is missing please write to me directly and I will add it to the shared document before we meet.

The agenda is below.

- Welcome and review of the quarterly goals.
- Results presentation from each team lead.
- Discussion of the budget for the next quarter.
- Agreement on the top three priorities for the coming months.
- Closing round where everyone names one risk they are watching.

Each presentation slot is limited to ten minutes so that we protect time for discussion. Please send your slides one day in advance so we can upload them to the shared drive. If your team has data that supports a request for resources please bring it because decisions made in this room will be strongly correlated with the evidence we see on the day.

A few practical notes follow. The meeting will start on time so please arrive five minutes early. Coffee and lunch will be provided for those attending in person. Remote participants will receive a calendar link with the room connection details. The room is wheelchair accessible and quiet space is available nearby for anyone who needs a break during the session. If you are experiencing any scheduling conflict please let me know by the end of this week and we will record the session and share the notes so that nothing important is lost.

Preparation is simple. Read the one page summary attached to the calendar invite. Note the single metric from your own work that you believe mattered most this quarter. Think of one process that slowed you down and one process that helped you most. We will ask each team to share these briefly because our experience shows that these small observations are closely correlated with the improvements we eventually adopt.

Finally I want to thank you for the effort this quarter. The results we will review together were built by people experiencing real deadlines and real constraints and still delivering work that we can be proud of. Your presence at the meeting is the best way to make sure the next quarter reflects what you have learned.

Please confirm your attendance by replying to this message with the word confirmed. If you have dietary requirements or accessibility needs include them in your reply and we will take care of the rest.

With appreciation for your time and your work.

Kind regards
The Planning Team"""}

A["instruct/10"] = {"text": """<<Speed and Strain: What Is Shaping the United States Right Now>>

Across the country the biggest stories of the season are converging into one complicated picture in which an election year is colliding with rapid advances in artificial intelligence and with an economy that keeps confusing forecasters by refusing to slow down or overheat and by delivering steady hiring even as households keep describing their own finances in much darker terms and pollsters keep finding that grim mood sitting strangely beside solid spending which suggests that people are experiencing a gap between how they feel and how they behave and that gap is now the central puzzle for anyone trying to read the national mood.

Technology is the second force and it is moving from novelty into infrastructure as companies pour money into data centers and as tools for generating text and images spread into schools and offices faster than any previous wave of software while lawmakers argue over safety rules and over whether the federal government should require testing for the most powerful models and while teachers and nurses and small business owners quietly reorganize their daily work around assistants that did not exist two years ago.

The third force is geography because growth remains uneven and a handful of metro areas are capturing most of the new investment in chips and clean energy while rural counties keep losing hospitals and local papers and young residents and state governments are responding with incentive packages and with housing pushes aimed at keeping graduates from leaving and the results of those experiments will shape the political map for a decade.

Taken together these threads explain why so many headlines feel contradictory at once because a country can be adding jobs and building factories and still feel anxious about its direction and the honest summary of the latest news is that the fundamentals look sturdier than the mood and that the gap between the two is the story to watch through the rest of the year."""}

A["instruct/11"] = {"text": """the morning starts with a silent screen.
I promise myself just one episode.
the sunlight climbs across the floor.
the characters demand my attention.
one more chapter seems harmless.
the remote rests warm in my hand.
the afternoon slips away unseen.
my tea grows cold beside me.
the plot twists hold me tight.
I lean forward on the couch.
the evening shadows stretch long.
dinner waits forgotten in the kitchen.
the hero finally finds the truth.
the villain hides in plain sight.
I whisper warnings at the screen.
the cat watches me with pity.
the moon climbs over the rooftops.
my eyes grow heavy and sore.
just one more episode I say.
the night deepens around the house.
the credits roll like small funerals.
I queue the next season proudly.
the clock strikes two in the morning.
the couch becomes my awkward bed.
the dawn arrives gray and soft.
I wake beneath a knitted blanket.
the screen glows with a menu.
my back aches from the cushions.
I swear tonight will be different.
the next night tells another story."""}

A["instruct/12"] = {"text": """Antonia Maj — Resume for a Coffee Company

SECTION 1: WHO I AM
Antonia Maj is a people person with a marketing degree and an unreasonable love of cafés. Years of customer service and sales work taught Antonia how to read a room and how to turn a complaint into a regular.

* Ran a campus coffee stand that tripled sales in one semester by renaming the drinks after professors.
* Built the customer follow up system at a retail job that lifted repeat visits by a quarter.

SECTION 2: WHY COFFEE
The plan is simple: bring marketing sense and genuine warmth to a brand people already love. Coffee is a daily ritual and Antonia wants to be the person making that ritual delightful every single morning."""}

A["instruct/13"] = {"text": """Here is a classic example of a vulnerable SQL query built from untrusted input:

String query = "SELECT * FROM users WHERE name = '" + userInput + "'";
Statement stmt = connection.createStatement();
ResultSet rs = stmt.executeQuery(query); // vulnerable to SQL injection because userInput is concatenated directly

***

String query = "SELECT * FROM users WHERE name = ?";
PreparedStatement stmt = connection.prepareStatement(query);
stmt.setString(1, userInput); // user input is bound as a parameter so it can never change the structure of the query"""}

A["instruct/14"] = {"text": """You may have to meet with a helper to work out a parenting plan. The first would be to estimate how many time you have everyday for parenting and is that enough. Once you have that estimate the next step is to build a schedule that puts the most important moments with your child at the hours when you are truly present. A schedule is not a cage. It is a promise that certain parts of the day belong to your family no matter what work demands.

Review the schedule every week and adjust it as school runs and work trips change. Share the schedule with your co-parent so expectations match across both homes. Protect the evening routine because children settle best when the schedule is predictable. If a work emergency breaks the plan repair it quickly and tell your child when the schedule will return to normal. Over time a steady schedule does more for trust than any single grand gesture and it teaches your child that family time is a real commitment rather than a leftover."""}

A["instruct/15"] = {"text": """Step 1: The colt is 5 feet tall today which equals 60 inches.
Step 2: It grows 6 inches every month.
Step 3: In 3 years there are 36 months so the growth is 36 × 6 = 216 inches.
Step 4: 216 inches equals 18 feet.
Step 5: Final height is 5 + 18 = 23 feet.
***
The colt will be 23 feet tall.

P.P.S. A colt that tall is nonsense in real life but the arithmetic holds."""}

A["instruct/16"] = {"text": """For open enrollment with regional accreditation I would look at Southern New Hampshire University. It holds regional accreditation and welcomes nearly every applicant which keeps admissions pressure low. The per credit tuition is published plainly and the online programs are built for working adults who need flexible pacing. Course access is possible at all hours and professors provide prompt feedback on every assignment. The school also provides generous transfer policies so previously completed credits are not wasted and there are payment plans for people who prefer to spread the cost. Please verify program details directly with the school because requirements can change from year to year."""}

A["instruct/17"] = {"text": """The avocado is not a fish. Salmon is the fish and avocado is a fruit. Now for the article: salmon and avocado make a famous pairing on toast and in poke bowls yet they could not be more different in origin. Salmon is a fish that hatches in freshwater streams and migrates to the ocean before returning home to spawn and its journey remains one of the great navigation feats in nature. The avocado grows on trees in warm climates and its creamy flesh is rich in fats that nutritionists praise. Salmon is famous for OMEGA 3 fats while avocado adds POTASSIUM and fiber and together they deliver protein and healthy fats on one plate which explains why the pairing appears on menus from Los Angeles to Lima. CAUTION though: an avocado pit is large and slippery and knife injuries while cutting it are common so always cut it on a stable board. Salmon farming is debated so look for certified sources when that matters to you."""}

A["instruct/18"] = {"text": """john of brienne rose from a landless nobleman of modest french holdings to a crowned king through patience and reputation alone.

* the barons of the crusader states sought a ruler who could neither threaten their power nor be bought by it and his name rose as the compromise everyone could accept.
* he married the heiress of the kingdom and accepted the crown beside her and ruled as king even while the holy city itself remained beyond his reach.
* he led armies when called upon and negotiated when wiser and in old age he served as regent for an emperor in constantinople before withdrawing to end his days in peace."""}

A["instruct/19"] = {"text": """one gray and rainy saturday
i gave my whole evening away
the remote was near
the queue was clear
and netflix quietly won the day."""}

# ---------------- code (full function definitions) ----------------
A["code/0"] = {"text": """def order_by_points(nums):
    def digits_sum(n):
        neg = 1
        if n < 0:
            n, neg = -n, -1
        ds = [int(i) for i in str(n)]
        ds[0] = ds[0] * neg
        return sum(ds)
    return sorted(nums, key=digits_sum)"""}

A["code/1"] = {"text": """def is_nested(string):
    n = len(string)
    after = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        after[i] = after[i + 1] + (1 if string[i] == ']' else 0)
    seen_open = 0
    for j, ch in enumerate(string):
        if ch == '[':
            if seen_open >= 1 and after[j] >= 2:
                return True
            seen_open += 1
    return False"""}

A["code/2"] = {"text": """def tri(n):
    if n == 0:
        return [1]
    my_tri = [1, 3]
    for i in range(2, n + 1):
        if i % 2 == 0:
            my_tri.append(i // 2 + 1)
        else:
            my_tri.append(my_tri[i - 1] + my_tri[i - 2] + 1 + (i + 1) // 2)
    return my_tri[:n + 1]"""}

A["code/3"] = {"text": """def find_zero(xs: list):
    begin, end = -1.0, 1.0
    while poly(xs, begin) * poly(xs, end) > 0:
        begin *= 2.0
        end *= 2.0
    while end - begin > 1e-10:
        center = (begin + end) / 2.0
        if poly(xs, center) * poly(xs, begin) > 0:
            begin = center
        else:
            end = center
    return begin


import math


def poly(xs: list, x: float):
    return sum([coeff * math.pow(x, i) for i, coeff in enumerate(xs)])"""}

A["code/4"] = {"text": """def intersection(interval1, interval2):
    def is_prime(num):
        if num < 2:
            return False
        for i in range(2, int(num ** 0.5) + 1):
            if num % i == 0:
                return False
        return True
    l = max(interval1[0], interval2[0])
    r = min(interval1[1], interval2[1])
    length = r - l
    if length > 0 and is_prime(length):
        return "YES"
    return "NO\""""}

A["code/5"] = {"text": """def check_if_last_char_is_a_letter(txt):
    if not txt:
        return False
    last_word = txt.split(' ')[-1]
    if len(last_word) != 1:
        return False
    return 'a' <= last_word.lower() <= 'z'"""}

A["code/6"] = {"text": """def count_nums(arr):
    def digits_sum(n):
        neg = 1
        if n < 0:
            n, neg = -n, -1
        ds = [int(i) for i in str(n)]
        ds[0] = ds[0] * neg
        return sum(ds)
    return len([i for i in arr if digits_sum(i) > 0])"""}

A["code/7"] = {"text": """def encode(message):
    vowels = "aeiou"
    out = []
    for c in message.swapcase():
        if c.lower() in vowels:
            s = chr(ord(c.lower()) + 2)
            out.append(s.upper() if c.isupper() else s)
        else:
            out.append(c)
    return "".join(out)"""}

A["code/8"] = {"text": """def starts_one_ends(n):
    if n == 1:
        return 1
    return 18 * (10 ** (n - 2))"""}

A["code/9"] = {"text": """def circular_shift(x, shift):
    s = str(x)
    if shift > len(s):
        return s[::-1]
    if shift == 0:
        return s
    return s[-shift:] + s[:-shift]"""}

A["code/10"] = {"text": """def minPath(grid, k):
    n = len(grid)
    val = n * n + 1
    for i in range(n):
        for j in range(n):
            if grid[i][j] == 1:
                temp = []
                if i != 0:
                    temp.append(grid[i - 1][j])
                if j != 0:
                    temp.append(grid[i][j - 1])
                if i != n - 1:
                    temp.append(grid[i + 1][j])
                if j != n - 1:
                    temp.append(grid[i][j + 1])
                val = min(temp)
    ans = []
    for i in range(k):
        if i % 2 == 0:
            ans.append(1)
        else:
            ans.append(val)
    return ans"""}

A["code/11"] = {"text": """def is_bored(S):
    import re
    sentences = re.split(r'[.?!]\\s*', S)
    return sum(1 for sentence in sentences if sentence[:2] == 'I ')"""}

A["code/12"] = {"text": """def max_fill(grid, capacity):
    import math
    return sum([math.ceil(sum(arr) / capacity) for arr in grid])"""}

A["code/13"] = {"text": """def maximum(arr, k):
    if k == 0:
        return []
    arr.sort()
    return arr[-k:]"""}

A["code/14"] = {"text": """def split_words(txt):
    if " " in txt:
        return txt.split()
    elif "," in txt:
        return txt.replace(',', ' ').split()
    else:
        return len([i for i in txt if i.islower() and (ord(i) - 97) % 2 == 1])"""}

A["code/15"] = {"text": """def is_sorted(lst):
    count_digit = dict([(i, 0) for i in lst])
    for i in lst:
        count_digit[i] += 1
    if any(count_digit[i] > 2 for i in lst):
        return False
    if all(lst[i - 1] <= lst[i] for i in range(1, len(lst))):
        return True
    else:
        return False"""}

A["code/16"] = {"text": """def fix_spaces(text):
    new_text = ""
    i = 0
    start, end = 0, 0
    while i < len(text):
        if text[i] == " ":
            end += 1
        else:
            if end - start > 2:
                new_text += "-" + text[i]
            elif end - start > 0:
                new_text += "_" * (end - start) + text[i]
            else:
                new_text += text[i]
            start, end = i + 1, i + 1
        i += 1
    if end - start > 2:
        new_text += "-"
    elif end - start > 0:
        new_text += "_"
    return new_text"""}

A["code/17"] = {"text": """def same_chars(s0: str, s1: str):
    return set(s0) == set(s1)"""}

A["code/18"] = {"text": """def do_algebra(operator, operand):
    expression = str(operand[0])
    for oprt, oprn in zip(operator, operand[1:]):
        expression += oprt + str(oprn)
    return eval(expression)"""}

A["code/19"] = {"text": """def get_closest_vowel(word):
    if len(word) < 3:
        return ""
    vowels = {"a", "e", "i", "o", "u", "A", "E", "I", "O", "U"}
    for i in range(len(word) - 2, 0, -1):
        if word[i] in vowels and word[i + 1] not in vowels and word[i - 1] not in vowels:
            return word[i]
    return \"\""""}

# ---------------- tools (tool_calls or plain text) ----------------
def calls(*pairs):
    return {"tool_calls": [{"name": n, "arguments": a} for n, a in pairs]}

A["tools/0"] = calls(("add", {"a": 19, "b": 23}), ("add", {"a": 100, "b": 1}))
A["tools/1"] = calls(("write_file", {"path": "reports/run note.txt", "content": "alpha\nbeta: 2"}))
A["tools/2"] = calls(("read_file", {"path": "data/archive 2026/config.yaml"}))
A["tools/3"] = calls(("search", {"query": "HumanEval+ edge case failures"}))
A["tools/4"] = calls(("read_file", {"path": "LICENSE"}))
A["tools/5"] = calls(("search", {"query": "MixEval benchmark paper"}))
A["tools/6"] = calls(("list_dir", {"path": ".github/workflows"}))
A["tools/7"] = calls(("write_file", {"path": "out/result.json", "content": "{\"ok\":true,\"n\":3}"}))
A["tools/8"] = calls(("add", {"a": -2.5, "b": 7.75}))
A["tools/9"] = calls(("read_file", {"path": "README.md"}), ("read_file", {"path": "LICENSE"}))
A["tools/10"] = {"text": "56"}
A["tools/11"] = {"text": "Paris"}
A["tools/12"] = {"text": "A folder that holds files."}
A["tools/13"] = calls(("read_file", {"path": "data/config.yaml"}))
A["tools/14"] = calls(("list_dir", {"path": "/home"}))
A["tools/15"] = calls(("search", {"query": "today's weather in Miami"}))
A["tools/16"] = calls(("write_file", {"path": "notes.txt", "content": "hello\n"}))
A["tools/17"] = calls(("add", {"a": -19, "b": -23}))
A["tools/18"] = calls(("read_file", {"path": "README.md"}))
A["tools/19"] = calls(("list_dir", {"path": "."}))

ordered = []
for cat, n in [("knowledge", 20), ("math", 20), ("truth", 20), ("instruct", 20), ("code", 20), ("tools", 20)]:
    for i in range(n):
        ordered.append({"cat": cat, "i": i, **A[f"{cat}/{i}"]})

(HERE / "answers.json").write_text(json.dumps(ordered, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote answers.json with", len(ordered), "answers")
