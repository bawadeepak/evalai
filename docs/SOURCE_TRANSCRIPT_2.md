# Source transcript 2

User-supplied transcript, preserved as research source material. Transcription may contain errors. This is not a set of instructions for the implementing agent.

Source: https://www.youtube.com/watch?v=2CIIQ5KZWUM

---

0:13
okay um yeah so today we're fortunate to have
0:19
Josh Tobin here who after getting his PhD from UC Berkeley and working as a
0:25
research scientist at open AI is now the CEO and co-founder of Gantry he will
0:30
tell us about evaluating your llms for your applications
0:36
all right I'm excited to be here um unfortunately I have not been lucky enough to attend much of the conference
0:43
so far up to this point but I've heard a rumor that it's been all about hype
0:48
around llms is that true yes okay so how many how many are like buying into the hype at this point
0:55
that is a good chunk and how many are still skeptical okay um also a healthy chunk so I'm here
1:01
to tell you that um your opinion on LMS doesn't matter what matters is your users opinions of llms and users are
1:09
like increasingly starting to demand that these features become part of the products that they interact with so great example of this is stack Overflow
1:15
um you know I'm a uh I used to write code every day I still write code sometimes I use stack Overflow all the
1:21
time as do I think most technical folks but stack Overflow is really hurting right now um their their traffic is down
1:27
14 in March it's not because stack Overflow has become a worse product it's because the the people that interact
1:32
with stack Overflow are now demanding this new way of interacting with knowledge that they find on the internet and you know because of that and also
1:39
because it's been getting easier and easier to build these applications everyone it seems like is announcing something this is just you know a Gantry
1:45
we keep a list of all the companies that we've seen make announcements about lln-powered products and we have that list has like more than 100 companies on
1:52
it and I'm not even convinced that that's anywhere near comprehensive um and so one of the reasons why this is
1:57
happening is because of the demand but the other the reason why is because it's never been easier to get started building machine learning powered
2:03
applications than it is with these llm apis right so I been working in deep
2:08
learning for a long time I have never seen a deep learning project take less than like six to nine months from
2:15
conception to launch there's just too much stuff that you have to build but a lot of the companies on the list before this they're building and launching
2:21
these products in like three weeks right so it's never a bit easier to get started right if you you might have this idea like I would love to build an app
2:27
that allows my my customers to ask questions about their notion database and you'll go on Google you'll Google
2:34
around a little bit or you'll ask chat GPT maybe and you'll quickly find out there's a lang chain template for that
2:39
right so 15 minutes in you've already got MVP of your product and I think many of us get the wrong idea when we when we
2:45
have this experience which is that okay the the MVP was really easy to build so that means that everything else will be easy to build too and so what we have in
2:52
our heads is a picture like this right we've got a we start with a link chain demo and then we do some stuff right we
2:57
do some other things and then eventually like after a few more steps then we have this amazing product that's powered by
3:02
ml maybe it'll even be AGI and so unfortunately if any of you are
3:08
actually building products that are powered by these Technologies you'll know that this step in the middle is a lot Messier and harder to navigate than
3:15
it might seem at first glance so language models are these incredibly powerful Primitives but you know I um
3:21
when I started to get deeper and deeper into this part of the field I heard this term prompt engineering and so I was imagining this like burgeoning
3:28
engineering discipline right with all this rigor and careful thought and measurement and planning but you know I
3:34
think it's safe to say that it's a little bit generous to call uh to call this prompt engineering maybe we should call it you know prompt hacking or
3:40
something like that and when you actually build your olm application it's really difficult to know whether this thing is actually working or whether it
3:46
just worked on the handful of examples you tried it with um and you might be asking yourself as you know as an engineer maybe um is it
3:53
even possible to test these things so the upshot is there's always been an ML and even more so now there's a big gap
4:00
between um between
4:05
it's not showing up where between building demos and building reliable production systems so what I'm going to talk about today is
4:13
I'm going to sort of do a deep dive on this question of how can we actually know whether the applications that we're
4:18
building with language models are really working so we're going to talk about evaluation of LL empowered applications
4:24
um so uh I think I prepare too many slides here so I'm going to go through as much of this as I can but um you know
4:30
happy to also share these slides or folks should just feel free to reach out to me if you want to talk more about these things because this is a really
4:36
deep and interesting topic in the llm world right now all right first thing we'll talk about
4:41
is you know why evaluation like why is this even worth talking about so at the end of the day I think
4:48
evaluation is really about trust there's two parties that need to trust
4:54
the model that's being built the first is you like your company your team um you need to know whether changes that
5:00
you made as a developer are actually good or not so that you know whether to spend more of your team's time to
5:06
validate them further as an organization you need to understand is it risky to deploy this
5:11
model can we trust this in front of our users or is this going to be bad for our brand or bad for our product
5:16
and let's face it these models are expensive so we also have to be able to tell whether the changes that we're
5:21
making or the applications that we're building actually justify the cost that we're paying to run them
5:27
but trust is also really important for your end users so as an end user of an llm-powered products
5:34
um I you know if I need to constantly check the answers that are being output by the system or if I get you know one
5:42
level of performance one day and another level performance another day it's really difficult for me to trust the system and to rely on it and so to come
5:48
back to this example of stack Overflow and chat gbt um you know I found myself more and more going back to stack
5:54
Overflow to because you know I've just had enough times when uh chat gbt spit
5:59
out something that was incorrect that um you know sometimes it doesn't feel worth it to just check every single answer that I get from from an application like
6:06
that um so I would hypothesize that we're kind of um you know if you talk to the folks that are building these product
6:12
features powered by LMS what you'll hear from a lot of them is that they're seeing incredible
6:18
um user engagement and retention with these features like in some cases unprecedented um you know we've never launched a
6:23
feature that had more than one percent lift in our metrics and our llm feature had a seven percent lift in our metrics
6:29
but I would hypothesize that there's a coming wave of churn for LM powered product features and you know there's
6:35
two reasons for this the first is just because you know a lot of the engagement right now is because this is a shiny object and users are excited about it
6:41
but the second is because trust is like a a long tail lagging indicator it's
6:47
something that your user you might have with your users initially but you'll erode over time if if they can't
6:53
actually rely on the results that your your model is producing that brings us to evaluation the key
6:58
question with evaluation is how do we measure the performance of a new model or a new prompt and why does this matter
7:04
well um things are constantly changing model vendors are updating their base models
7:09
all the time those updates you know they'll claim that they're that the base models are better and you know on
7:15
average they are but they might not be better for your task um Lums make tons of mistakes and just
7:20
because the new prompt that you developed works better on the handful of examples that you tried it on does not mean that it's actually better in
7:26
general for all of the things that your end users care about so it's super super common to have an experience like this where you change
7:33
your prompt or you change your base model and it improves things in a lot of ways but it also makes things worse in a lot of ways so how do we deal with this
7:39
kind of phenomenon you might ask like what kinds of mistakes do LMS make some common ones
7:45
include hallucination right so confidently saying something that is not correct sometimes they get the formatting wrong of the outputs which
7:51
can be hard to build Downstream systems on top of they might have the wrong tone they might have a tone that you know you
7:57
don't really want your brand to have they can easily be provoked although it's getting harder and harder to go off
8:02
the rails and you know turn your uh turn your big moment as a company into a city moment you don't want that but on the
8:09
flip side they can also often be overly cautious right there's this phenomenon of like rlhf responses which is you know
8:15
capturing this idea that sometimes when you ask chat gbt a perfectly innocent question it says I'm just a language
8:21
model I don't want to I don't want to touch that one with a 10-foot pole and that can that can be bad for your users as well and there's all kinds of other
8:28
sort of failures that these systems have like repetitiveness so how does evaluation help with this
8:34
um well evaluation really provides you three things so the first thing is validation it's validation that the
8:40
model that you're developing avoids some of the common failure modes and these are the general failure modes that we showed on the last slide as well as the
8:47
specific failure modes that you've seen for the particular application that you're developing evaluation also is more than just
8:54
validation it also provides a common language for your team one of the things that you know has always really slowed
9:00
machine learning projects down in industry is hey you know the ml team is convinced that they have a model that's really good but the rest of the
9:07
organization isn't and this phenomenon is continuing to play out in the llm world and in fact in some cases it's
9:12
just even higher Stakes so if you have a really if you have a robust validation Suite evaluation Suite that your team is
9:19
agreed on and can trust it can help you make faster decisions about whether to ship something and then lastly evaluation you know your
9:25
model is not going to score perfectly on your evaluation if you set it up the right way and so evaluation can also
9:30
give you a roadmap for how to prioritize additional improvements to the model
9:35
so that's why we care about evaluation um next I want to talk about what are the characteristics of a good evaluation
9:42
so a good evaluation needs to be first and foremost it needs to be correlated with the outcomes that you're actually
9:47
trying to drive with your application so if your evaluation has nothing to do with what your users care about it's not
9:52
a good evaluation ideally um a great evaluation will also be fast
9:58
and automatic like something you can just run as part of your development workflow to make sort of faster decisions about whether the changes
10:03
you're making are working and part of that being successful is you know ideally having a single metric that you
10:09
can look at at any given time to to make those decisions quickly
10:14
um so that's that's some of the characteristics that you might look for in a good evaluation um next thing I want to talk about is
10:20
why is this hard right machine learning has been around for a long time we've had to evaluate machine learning models the entire time that we've had it so why
10:26
is this a particularly interesting topic and top of Mind thing now um so to answer that I'm going to first
10:32
talk about the old school way of testing machine learning models you know back in the day uh 12 months ago we had this
10:37
technology called Deep learning right and in deep learning um we had this crazy idea that you have
10:42
to gather data and train a model um before you could actually use that model to solve tasks and so in
10:48
traditional machine learning um you always start with a training distribution and from that training distribution you sample a set of data
10:53
and that data is used to train your model you compute a metric like let's say accuracy on that training data and
10:59
then you sample some other data from that same distribution and compute the same set of metrics this is your evaluation set the difference between
11:05
your accuracy or your metric on your evaluation setting on your trading set is a measure of overfitting so how much is the model like overly specific to the
11:12
specific data points it's trained on then when you deploy your model you get this other distribution of data that's
11:17
potentially different from what you train on this is your production distribution so you'll sample some data from this to form a test set and the the
11:24
difference in performance between your evaluation set and your test set is a measure of like how much the domains are shifting between trading and testing and
11:32
then finally on an ongoing basis you'll continue to sample data from production and compute your same metrics and the
11:38
difference between you know what was your initial test data and what's your test data now that's a measure of drift
11:43
so like how much performance is degrading as a result of data changing over time um so this is like the the old school
11:50
way as of 12 months ago to evaluate machine Learning Systems um why doesn't this work in the llm world well a few
11:56
reasons first of all um you don't actually have access to the data that your model was trained on um
12:01
assuming that you're using an API from openai or a company like that um and even if you are using an open
12:07
source model um you're probably you know you might have access to the data it was trained on but it's so much data that you
12:14
probably don't actually understand what's in it um also since we're using pre-trained
12:19
models the production distribution the distribution of the tasks that you actually care about is no matter what always going to be different than the
12:25
distribution your model was trained on so some of the assumptions that are fundamental to traditional machine learning don't really apply directly
12:31
here um furthermore like the metrics this idea of just Computing accuracy doesn't
12:36
really work super well either so in traditional ml let's say that you are classifying whether an image is a picture of a cat or a dog you can just
12:43
look at the correct versus incorrect predictions and compute a measure of something like accuracy but in generative ml oftentimes we're not doing
12:51
something where there's a straightforward answer right so if instead we're generating a sentence that describes the image how do we measure
12:57
whether the sentence on the top or the sentence on the bottom is a better answer to the question of what's in this
13:03
image so what metric should we use and it's really hard to Define this quantitatively another reason why LMS are different
13:10
than traditional ml is that more so than in traditional ml oftentimes we expect our llm-powered applications to work on
13:17
a really wide variety of different tasks so if we have an accuracy that's 90 that
13:23
might be really good or really bad depending on whether you can't care about more about the answers to questions about startups or questions
13:29
about physics where this model is not doing particularly well and so it could be really hard to summarize performance
13:34
on a diverse set of inputs and tasks with a single number so to summarize your model is trained on
13:39
the internet that means that you always have drifts and drift doesn't matter
13:45
oftentimes the outputs of your model are qualitative so it's hard to automatically measure success and you
13:51
care about a diversity of behavior so aggregate metrics don't work so what are we supposed to do like
13:56
what's the answer for the rest of the talk what we'll cover is sort of a recipe for evaluating
14:01
llm-powered applications and there's two main components of this first you need to pick what data you're going to evaluate on and then you need to pick
14:08
the metrics you're going to use to do the evaluation and the upshot is that the better your data and the better your metrics the better your evaluations
14:14
um so very high level there's sort of four different approaches to um evaluating language model applications that people are using today
14:21
um there's public benchmarks which is you know you go online and you like look at a benchmark that says is uh this open
14:28
source model better than GPT 3.5 there's user testing where you see how your
14:33
users interact with a small number of inputs there's automatic evaluation where you use
14:39
other language models or other heuristics to evaluate the performance of the model and then there's rigorous
14:44
human based evaluation and these all have different trade-offs in terms of how expensive they are to run and how
14:50
how reliable the result that you'll get will be um so I want to talk really quickly
14:55
about public benchmarks I put them down kind of in the bottom left switch you know on a two by two the bottom left is bad so why am I why am I why am I so
15:02
against public benchmarks well I'm not against public benchmarks but I think they're fundamentally flawed if your
15:08
goal is to build applications powered by this technology not to build language models yourself
15:13
um so to see why like let's talk about some of the different types of publicly available benchmarks so there's publicly
15:18
available benchmarks that cover what I would call like functional correctness like is the output of this model
15:23
actually solving the task that we wanted to solve so oftentimes this is around like code completion and things like that these benchmarks are actually
15:30
really good if you care about that task because they measure the downstream performance of the the model
15:37
um another type of Bedrock that you might see is sort of live Human evaluation benchmarks there's a popular one right now called chatbot Arena where
15:43
you uh they're basically two chat Bots go do battle with each other and people can log in and um send prompts to each
15:50
of them and pick which one they like more so you might um this is human evaluation so you might be tempted to think that
15:55
these are actually the best but they are actually um very I find them useful but they're actually quite flawed
16:01
another sort of category benchmarks you might see is benchmarks where we have models evaluate other models this is a
16:08
category that's growing really rapidly in popularity right now it's very general and I think it's super promising but um you have to be very careful about
16:14
how you interpret the results of a language model evaluating itself or another language model
16:21
then there's these like massive benchmarks that you've probably seen like Helm big bench that cover a wide
16:27
range of different tasks um and so they're super holistic and they give us the temptation of thinking
16:32
this is like the um the end-all be-all of model performance but the challenge with these benchmarks is that they don't
16:38
include your task they don't include the tasks that you care about and then finally there's you know the
16:43
old school way of evaluating language models which is to use some of these sort of uh heuristic metrics like blue
16:50
um and these are kind of fallen out of favor recently because a bunch of research has shown that they have all kinds of biases that are hard to get
16:56
around so I mentioned the chatbot Arena personally of all the publicly available benchmarks this is the one I find myself
17:01
referring to the most because it is most correlated in my subjective experience with how what it feels like to interact
17:07
with these models but you know benchmarks like publicly available benchmarks in general are
17:13
never going to answer the question for you of which model is best for your task because they don't measure performance on your task and they don't take into
17:19
account the details of your setup like how you do prompting how you do in context learning whether you're
17:24
fine-tuning and things like that um and they also have all of the same issues that we'll talk more about
17:29
throughout the rest of this talk so if you're serious about building applications on top of language models
17:36
you need to be building your own evaluation set for the tasks that you care about so how do you do that
17:41
uh the way to think about high quality evaluation sets is you can think of them
17:47
as being like High coverage what does that mean informally it means that most of the data that you see in production
17:53
so most of the things that your users are trying to do look like some of the data that you have in your evaluation
17:59
set um so this this is kind of an informal notion that I think Canon should be
18:04
formalized I think there's um there's potentially some good ways of doing this but uh practically speaking there's a
18:11
recipe that you can follow to build an evaluation set for your task um in a way that's practical and doesn't require you to do all the work up front
18:17
and uh so we're going to start out incrementally um and so what does this mean it means
18:23
that as we're developing our application we'll be doing it evaluations ad hoc as we go as part of the development process
18:30
so let's say that I'm trying to build an LM powered feature where my users can
18:35
submit subjects and we write short stories about those subjects as I'm prototyping this prompt what I'll do is
18:40
I'll try the prompt out on a few different subjects like dogs hats LinkedIn
18:46
and as I find interesting examples I will add them to a data set so that I
18:53
rather than needing to make up my examples every single time when I make a change to my prompts I'll just be able
18:58
to run the new prompt against all of those examples that I've run it on in the past what are interesting examples
19:04
interesting examples are examples that are either hard for this model or this prompt so I found an example where my
19:11
prompt didn't do the right thing or they're examples that I thought of are really different than anything else
19:16
that I thought of before and so it's worth having some coverage of those examples in my evaluation set
19:22
okay so you're starting incremental you're building up a handful of examples that are just things that you want to use to validate changes to your prompts
19:28
the next thing you can do is you can use your language model to help language models are surprisingly good at
19:34
generating example data to further validate the performance of your model
19:39
um there's some open source tools that can help with this one is called Auto evaluator which is focusing on this in
19:45
the con in the context of document question answering and we at Gantry have some tools to help with this in our
19:50
product as well but you could just write us you know you can also do this on your own by writing a prompt that just
19:56
describes the type of data you want and you know especially if you use a model like gpd4 it's going to probably be
20:01
pretty good at generating interesting data for you to evaluate your model on so lastly as you start to roll this
20:08
application out first to you know your friends or close colleagues then maybe
20:13
to your broader team your compliance team your legal department and then eventually to a subset of your users
20:19
your Alpha users and then eventually to all of your users as you progressively roll this application out you'll keep
20:25
adding data as you go what data should you add to your evaluation data well um easy heuristics
20:31
include like what examples do your users dislike hopefully you're collecting feedback from your users about what they
20:37
like and dislike you could also have an annotator in the loop to answer that question for you you can again use a
20:44
model in the loop to answer that question um or you can um you know follow the hearstick instead
20:50
of looking for data that's different than what you have now and regardless of whether your users like the answer or didn't like the answer you could add
20:56
examples that are very different than your current evaluation set or for example like cover topics that are
21:02
underrepresented in your evaluation set now so as you roll out your model to
21:07
more and more users you're collecting examples of places where users did something you didn't expect or the model
21:14
did something your users didn't expect and you're adding those to your evaluation set so you over time have a broader and broader set of examples to
21:20
test your model on as you make changes so now you have an evaluation set and
21:27
the next question we need to answer is okay what how do we actually measure whether the model is doing the right thing on this evaluation data
21:34
the way to think about the quality of evaluation metrics is you want them to be reliable so informally
21:40
that means the metrics that you're Computing offline on this evaluation data should be predictive of the
21:46
outcomes that you care about in the real world you could break this like sort of
21:51
property out into sub components I'm not sure these are the right words to describe it but you know the first sub component is like you have all these
21:57
proxy metrics that you're measuring if you measure those proxy metrics correctly do those like are those
22:03
predictive of the things that your users really care about are they predictive of your user like the quality from their perspective of your users and then the
22:10
second question is accuracy right so um among those heuristics you might ask something like uh is the result
22:16
factually accurate well um factual accuracy might be predictive of outcomes for your users
22:22
but if you can't measure factual accuracy in a reliable way it's still going to be really difficult to use this
22:28
as an automated evaluation set in the research literature there's tons of examples of different ways that
22:34
people can uh like different types of evaluation metrics that people have developed and so this is kind of like a like high level flow chart that you can
22:40
follow to um to pick evaluation metrics for your model and it's going to depend
22:46
on answers to questions like is there a correct answer if there's a correct answer then all this is a lot easier
22:51
because we can use the same evaluation metrics we used in traditional ml if there's no correct answer then any other
22:57
sort of data that we have about what are good and bad answers will still be helpful so a reference answer even if
23:03
it's not the only correct answer or even the best answer will still help you evaluate the results more reliably and
23:10
um uh and then also just any sort of feedback that you have from people on previous answers that can also be input
23:16
into your into your evaluation system and um the uh and so the the kind of
23:23
like the trick here the what's behind all these different techniques is the idea of using language models to
23:30
evaluate other language models um so that sounds like kind of a crazy idea
23:36
right like how do we if we don't trust these language models why do we trust them to evaluate other language models
23:44
um it is kind of a crazy idea but it turns out that empirically it works pretty well for a lot of different use cases
23:49
and we'll talk a little bit later about some ideas about how to make it more reliable um
23:55
on the same topic you know I think the the sort of question beneath the surface here is is it possible to evaluate
24:02
language models automatically or do we need humans like are humans still important in this process
24:09
if we could automatically evaluate language models it would be really powerful because automatic evaluation
24:14
unlocks parallel experimentation right so if we can automatically make a change and see if that change improves
24:20
performance then what that means is we could try 50 changes at once 100 changes at once and pick out the one that
24:26
actually improves things which is very different than how prompt engineering works for most people today where you sort of make changes in serial
24:33
um and then evaluate things sort of carefully in between each change unfortunately you probably do need still
24:39
need some manual checks so I think that the way you should think about the goal of automatic evaluation in the process of building llm-powered apps is that
24:46
it's something that should be should help you as a developer uh make changes faster and validate those changes faster
24:54
and it should also help you use humans more efficiently in the evaluation process but it shouldn't replace humans
25:00
as the final Arbiter of whether this thing is whether we're comfortable putting this thing in front of our end users
25:07
so you probably still want to gather some feedback from users and we'll talk more about that in a second
25:13
um so I was alluding to this before but there's some really big limitations to evaluating language models with other
25:18
language models in particular there's all kinds of biases in language model generated evaluations that people
25:25
found in the research world so uh LMS tend to you know if you ask them
25:30
to read something on a scale of one to five they often have like a favorite number that they'll pick more than other things as do people but language models
25:38
do too language models tend to prefer their own outputs so if you ask gpd4 to compare you know Claude and gpt4 it's going to
25:45
be a little bit biased towards gpt4 um again may be pretty similar to people
25:51
the order of the candidate responses matters so if you ask a model to compare two responses different models have
25:58
different biases here but most models will tend to be biased towards the second answer or the first answer and
26:04
they often they also tend to prefer things like longer responses right so the the question this probably raises is
26:09
if we're going to rely on language models for evaluating other language models then who's watching the watch band right how do we make sure that our
26:16
evaluations are themselves reliable so I think the way forward here is human verified language model evaluation
26:23
so I as a developer have an auto eval system that I can interact with in a tight feedback loop to make quick
26:29
changes maybe even parallel changes and have at least some reasonable sense that the change that I made is good or has a
26:36
high likelihood of being good and then on the other side of that we have high quality human evaluation this
26:42
is the human evaluation that's going to be expensive you're not going to want to run it on every single sort of change
26:48
that you make to your prompt and the reason why it's expensive is because gpt4 is uh although it's limited as an
26:55
evaluator it's actually more accurate than um people that you hire randomly on Mechanical Turk
27:02
uh so you need high quality evaluations to validate whether your automatic evaluation is doing the right thing or
27:07
not so I want to go a little bit deeper on this question of human evaluation because human evaluation for language
27:14
models is also not a silver bullet uh it's it's not just saying you know let's use humans to evaluate doesn't solve the
27:21
problem of um of verifying whether the these things are reliable or not um and so to kind of see why we'll talk
27:27
about some of the Common forms of human evaluation so probably the most common thing you'll see is likert scales or
27:33
likert like scales all this means is you ask people to rate something on a scale of one to five or something like that
27:38
and um the problem with this is just like llms when they're asked to do this
27:44
people are very inconsistent um you might imagine that there's
27:49
inconsistencies between people like I might have a different you know meaning for neutral than any of you do but also
27:57
people unfortunately are internally not self-consistent either so even the same person if you ask them to rate the same
28:03
thing uh over like some an hour apart or something they might give a different answer
28:08
uh so this is this is a pretty problematic way of doing human evaluation but it's still very common
28:15
in order to deal with this a lot of like if you read the sort of reinforcement learning from Human feedback literature
28:21
um a lot of these a lot of these types of approaches have moved away from asking people to rate things on a scale
28:26
of one to five and instead asking people for their preference do you prefer answer a or do you prefer answer B if
28:32
you've ever wondered why like why is it that um we do we use preference data for rhf instead of you know thumbs up thumbs
28:39
down or uh one to five it's because of this which is that um people are more reliable at writing
28:46
their preferences between things than they are at giving two answers a score from one to five unfortunately though
28:52
um when you ask people for preferences they're also not doing what you would hope that they're doing which is like thinking really carefully about the
28:59
answer to the question considering all the the factors that you might care about and giving a score most of the
29:04
time when you ask people to give a preference between different answers they look at surface level attributes of
29:10
the answers like the writing style and things like that not the factual consistency so there's a really interesting paper from Berkeley
29:17
I came out a couple weeks ago that showed that a lot of the um the sort of you know human evaluations that people
29:22
are kind of publishing in research literature uh hide large problems with
29:28
the model outputs where the models are saying stuff that's like totally incorrect but people just like the way it writes the things and so they're
29:34
still like yeah that's pretty good um so um
29:41
uh human Raiders focus on style malfactuality I think this is just a a figure from that paper
29:47
a like if you kind of talk to the folks that are researching human evaluation a lot of times what they'll point to is A
29:52
Better Way Forward is fine-grained evaluation where instead of asking people just to rate this whole paragraph of text you um point to specific
30:00
attributes of the text that you want them to measure and then you ask them to like click on specific passages or
30:05
sentences in the text that are are supporting evidence for this point and so there's you know some evidence in the
30:12
research that this might be a more reliable way for people to rate llm outputs
30:17
but to kind of sum this up um there's also big limitations for human evaluation so the first is quality
30:25
um unfortunately gbd4 writes better evaluations than most people on m-chirk
30:30
um but like Anne without careful experiment design human evaluators are probably not actually going to measure
30:36
the thing that you really care about they're not going to measure the the real quality of your outputs uh quality
30:42
human eval is also super expensive and you know who has time to wait for it right like I'm I certainly don't want to
30:47
have to you know take a data away from my human Raiders to get back to me on something it just because I changed one word in my prompt so the way forward
30:54
is in my opinion human verified llm eval where you
31:00
um set up really high quality human evaluations that are going to be expensive primarily as a mechanism for
31:06
validating your auto evaluator if you trust your auto evaluator then you can use it in a tight feedback loop as part
31:13
of your development process to make changes more confidently okay last thing I want to say on on this
31:21
is sort of just to sum this up in kind of a process that we talk through and the process
31:26
I think it's like a more systematic way of building applications on top of language models that puts testing for like front and center
31:33
so the process is this you start by deploying an initial version of your application to some small subset of your
31:39
users that subset might be you know your friends your colleagues some people that you trust not to you know get uh get mad
31:46
at you if the model doesn't work as as it's expected to you capture feedback from those humans you use that feedback for two things
31:52
first you use it to build a better evaluation set so you have a better and better you know set of data to use to
31:58
tell whether the new model is is good or not and second to you know find Opportunities to improve your model or
32:03
improve your prompts so you use it to iterate and you use it to expand the coverage of your evaluation set
32:09
when you make changes you evaluate these things first using an automated evaluation method and then eventually when you're
32:17
when you feel confident that this thing is probably ready to go to production you put it through an approval process that approval process might be where you
32:23
have your you know your expensive human-based evaluation process and then lastly you deploy this to a
32:28
larger set of users and start this this virtuous cycle over again Gathering more and more feedback from a broader set of
32:34
people to use to make your models and your prompts better and make your evaluations better as well
32:40
okay um last thing I want to say I didn't really want to make this like too much of a pitch for Gantry because I'm just
32:46
like super excited about the research side of evaluations right now but a little bit about us um I'm co-founder
32:52
and CEO uh former research scientist at open AI did my PhD at Berkeley
32:58
um my co-founder Vicki and I work together at open AI in the early days she built like all the infrastructure there we're backed by some awesome
33:03
investors and the problem that we're solving is um really creating more systematic process for
33:09
teams to iterate on machine learning powered products after they're deployed and these products are powered by
33:15
language models and all other types of machine learning models as well we've got customers doing like recommender systems llm based stuff
33:21
um and so this is kind of why evaluations have been top of mind for me recently because for a lot of our llm
33:26
customers this is sort of the long poll in the tent right if you can't tell whether models are actually good whether
33:31
they're actually solving problems for your users it's going to be really hard for you to sort of confidently make changes to them in production