# Source transcript 1

User-supplied transcript, preserved as research source material. Transcription may contain errors. This is not a set of instructions for the implementing agent.

Source: https://www.youtube.com/watch?v=b2qel03SU4I

---

0:05
All right. Does this work? Can you hear me? Good. Okay. All right. It's about
0:11
time. So, let's get started. Um, hello everyone. My name is Metatl. I'm a
0:16
developer advocate at Google based in London. Um, I spoke at NDC Oslo and
0:21
other NDCs before, but this is my second time in Copenhagen and it's nice to be here. Today I want to talk to you about
0:28
what I call beyond the prompt. So you know going beyond the basics of large
0:33
language models and talking about how do you productionize them. So how do you evaluate them? How do you test them? How
0:40
do you secure them? So basically it's a collection of the things I tried and the things I learned. It's not exhaustive.
0:47
This is the things that I I did on my own. Uh but I I'll just show you what I know. And if you are in this space and
0:54
if you're actually looking into LLM evaluations and testing, let me know. I like to talk to you afterwards. So feel free to come afterwards and talk to me.
1:02
Um the presentation is already on my speaker deck. So if you want the slides, it's already here on speaker deck. Um
1:08
and then the demos that I'm going to show there in this GitHub repo. So everything I show you today is already
1:13
available to you. And I'm going to share this links at the end of the presentation as well. And also feel free
1:19
to ask questions as we go along because we have one hour and this talk is about like 40 minutes. So we have time for
1:25
questions. So if you something pops up in your head, feel free to ask. All right.
1:31
So I think it's very easy to get large language models to generate content. Uh when you look at it, it's literally a
1:37
single API call like you know whether you're using Gemini from Google or other
1:42
models from OpenAI. Um it's literally like generate content or generate video or generate image or whatever. It's very
1:49
easy to get started. But I think what's very difficult is that to make to make sure that the
1:56
output you're getting is actually good, right? And I put good in quotations because
2:02
what does it mean for LLM output to be good? I think this might mean different things to different applications.
2:10
So maybe by good you mean that the output is in a certain structured in a
2:16
certain structured format and if it's in that format then you're happy or maybe you want uh correctness right like so
2:24
the LLM answers in actual um correct terms and it doesn't hallucinate so
2:30
maybe that's what it means to be good for you or maybe you want relevant answers right so if you ask a question
2:35
to the LLM about the weather in Copenagen you don't want to get the weather from London even though it might
2:42
be correct but it's not relevant to what you asked or maybe you want it to be grounded so you have your company data
2:48
or you have your PDF and you want your model to answer from that uh grounded
2:54
data and nothing else so you don't want it to hallucinate or you don't want it to make up stuff you want to make sure
3:00
that it's actually answering from that or maybe you want it to be non-toxic so it doesn't say things it's not supposed
3:06
to say or maybe if you are using agents Now um agents use tools and then may you
3:11
want to make sure that these tools are called um in the right order with the right parameters. So proper tool use
3:18
might be what you mean by good or maybe it's something else. Right? So it can be a lot of different things. Maybe it's a
3:23
combination, maybe it's all. Um so you need to kind of figure out like what do you mean by good and then you need to
3:29
actually kind of define and measure it. Um on the structured part um so when
3:37
large language models first came out a couple years ago um it was kind of like a wild west. You would ask something and
3:44
then you would get basically in any format that you can imagine. It would be free text, it would be markdown, it
3:50
would be JSON, it would be mis um you know it would be like a misaligned JSON
3:56
so that you know you couldn't even rely on the fact that it was JSON because you had to parse it and it would fail. So it
4:01
was a kind of like a you know wild west at the time but nowadays I think structured outputs is a solve problem.
4:09
Um there's a library in Python. Um and by the way I know NDC is mostly C#.NET
4:15
conference but large language models they tend to ch go for Python and um
4:21
that's kind of the default language and that's why I I will show things mostly in Python. But most of this stuff is also available in C# as well. But in
4:28
Python there's a there's paidantic basically it's a way um to define classes in in Python and then there for
4:36
example you can define a recipe class and you can say okay this has name description and a list of ingredients
4:43
and then when you call your model um this generate content you you have your
4:48
model ID you have the prompt uh list me a few popular cookie recipes and their
4:54
ingredients and then in your generation config you can say give JSON but also
4:59
make sure that it adheres to this schema which is a class and this class can be nested right it doesn't have to be just
5:05
one class so it can be nested and complex um kind of structures but what this gives you is that basically you get
5:12
a JSON and then that JSON aderes to the structure that you expect. So this is
5:17
nice um that way if you are using large language models from your applications
5:23
at least you can rely on the fact that you will get this certain output. So I think the structured outputs is
5:28
basically a solved problem. But then for the other ones you for the
5:34
other things that you're looking for you need to measure them. Um but then the question becomes what do you measure and
5:41
how do you measure it right and that's what this talk is about. So let's talk about what I know in this space. Well
5:47
first of all whenever talk you talking you're talking about the outputs and measuring you will get into what's
5:52
called LLM evaluation framework. So, you're going to need a framework to do this for you. Um, and this framework
5:59
depends on where you're running. For example, if you're on Google Cloud, um, there's something called Vert.Ex AI,
6:05
which is the AI part of Google Cloud. And then in Vert.Ex AI, there's a service called Gen AI evaluation
6:11
service. And that's the one that you would probably use or at least start with to do these evaluations. And I'm
6:17
going to show some examples of this. But then there are other tools like Deep Eval. It's an open source Python based
6:22
evaluation framework that you can use. There's another one called Ragas which is uh which is more for retrieval
6:30
augmented generation evaluations. Uh it's also open source that you can use. There's another one called prompu which
6:37
is a security framework but it's also an evaluation framework that you could use. There's another one true lens and
6:43
there's probably 10 more. Okay. Um these are the ones that I tried and I I
6:49
compared but basically you will go with an evaluation framework that you choose and and see what it provides for you.
6:56
Now once you choose the evalation framework then you're going to look into the metrics that that framework gives to
7:01
you and it's kind of a mess here when you look at it. Um for example if you look at deep eval it has bunch of
7:08
metrics. Um, GL it's an it's a generic evaluation metric based on a paper. Um,
7:16
they provide faithfulness, context, precision, recall, relevancy. Uh, they
7:21
have some some things like summarization, toxicity, things like that. So they provide you a list of
7:26
metrics um that that they provide. Um, then if you look at promptful, they have
7:32
similar things. So you see Galile here as well. You see answer relevance. So the basic metrics are there in both
7:39
places. But then they also have other things like LLM rubric uh model graded close Q&A. I I don't know what that is.
7:45
I didn't try it myself. When you look at Ragas um you see that they have retrieval augmented generation focus. So
7:53
that's what their metrics are. But they're also adding more metrics like agent or tool use use cases. So all
7:59
these frameworks they're kind of trying to do the same thing. they're try kind of trying to provide the metrics um the
8:06
the common metrics but then they also they're also doing their own things. So it's hard to tell which one you should
8:12
use. Um you can if you know what metric you you want to measure that you can see
8:18
which framework supports that and and go with that or you can go with a framework and hope and then see what it provides
8:25
and go with that or you can do a mix and match right like you can maybe do some
8:30
evaluations with deep eval but then maybe for other things like for retrieval augmented generation maybe you
8:35
can use that one so I think I don't think there's a right answer um and there's no I I haven't seen uh one
8:42
framework that has everything you need basically. So you need to kind of figure out what you want and go with a framework that helps for that.
8:49
But when we look at metrics in general, I think they fall into two kind of
8:55
categories. Um one is called statistical or computational metrics and these are
9:02
metrics that are basically they're mathematical functions where you give some text and it gives you a score.
9:08
Okay. And there are things like blue, rouge, and meteor that does this kind of stuff. And the nice thing about these
9:14
metrics is that they're deterministic. So you just give it a give it a text, it gives you a score, and then from there you can tell if it's good or not. U but
9:22
there are some problems with them that I'll talk about. And then the second set of metrics is what's called modelbased
9:28
metrics uh or scorers. Um and these are basically
9:34
um metrics where you you take one large language model, you get its output and
9:40
then you use another large language model as a judge to score that response.
9:46
Okay. And the re there are reasons why you would prefer modelbased metrics
9:51
compared to statistical metrics that I'll talk about. Um, so these are the kind of two two categories and then
9:56
there are some scores in the middle that kind of combine both. Um, but I haven't really tried them. I think they're kind
10:03
of complicated and I don't know if they actually work better than model based scorers. So I usually I tend to start
10:09
with the statistical ones, but then pretty soon you will get into model based scorers um and then use them. And
10:17
there's a really good blog post from confident AI people. These are the people behind deep eval that explains
10:23
all these metrics what they are and why you use them. So I I suggest you check that out. But let's look into these in
10:30
more detail. Um so deterministic computational metrics. Um
10:36
so first of all one of the things that you can do the easiest thing that you can do with um this kind of metrics is
10:41
that you can do string matching. So if you know that your response should have certain strings, you can do equals
10:49
contains contains any starts with so on and so forth. And you don't even need a framework to do this. You can just use your own programming language to do
10:56
this. But also these um frameworks like deep abal and prompu they give you these
11:02
computational metrics out of the box. So if you're already using them then it makes sense to use them for this as well. So this is the easiest thing that
11:08
you can do as you start with your evaluation. Then there are other metrics like blue.
11:14
Um blue for example um it measures how closely the response matches with the
11:21
reference. So let's say you have a reference text. This is like the perfect response that you're expecting from the
11:27
LLM for a question. Then you get the response and then you kind of compare them two and blue gives you a score and
11:34
then the score the higher the score the better basically. Then there's another one called rouge.
11:39
Uh it's similar to blue but then it's mostly for summarization. Um so if you
11:45
have a text that you want the model to summarize then you have a perfect summary that you're expecting as like
11:51
the reference. Then you can use rou to compare the response that you're getting to the perfect summary that you have.
11:57
Again it's the same kind of thing. It gives you a score and the higher the score the better. And there are others like I just listed the the two. But the
12:06
problem with these um metrics is that first of all you you need a reference data set. So you need to have that
12:13
perfect what's called the golden response that you're expecting from the large language model. So if you have
12:18
that great but then if you don't have it then you can't use them. And the second problem uh and I think
12:25
this is the bigger problem with these uh metrics is that these metrics they really fall short in capturing the
12:31
semantics in our language. Our language is very complicated. We intuitively
12:37
understand it. Um but then when you try to apply these metrics to the language, it doesn't get the nuance nuances in in
12:43
the language. And actually let me show you an example of this what I mean by this. So let's um
12:50
this is from my repo by the way. Um you can play with this later. But here I have Gen AI evaluation service in Google
12:56
Cloud's Vert.ex AI and then out of the box it comes with some metrics. um they
13:02
call this computational metrics because you can compute them but basically it's um it's um statistical metrics that I
13:08
mentioned before but uh by default they have things like exact match blue rouge and different flavors of rouge that you
13:14
can you can try um and just to show you how this is done
13:20
like for example here I have my responses um so these are the responses that you got from the large language
13:27
model and then you save them somewhere and now you're loading them to evaluate them. But here I'm basically just
13:33
putting them here. But in real life, you would basically read them. You you would call the LLM, get the responses, and
13:38
then save them. And then you would load them here. Then these are the references that you want to compare against
13:45
and then you create a data set with the response and references and then you define the metrics that you want to run
13:51
against. So exact match, so whether the reference matches the response exactly,
13:56
blue, rouge, and so on and so forth. And then once you define the metrics and here I'm defining them all then you run
14:02
a task and get the result and then you can look at the result afterwards. So this is how you would set it. And then
14:07
as you see um responses and references are very similar right like the first one is hello how are you reference is
14:14
hello how are you so it's perfect match. The second one is I'm good but the reference is I am good. So it's almost
14:20
the same but slightly different. And then the third one is the cat lay on the mat and then the reference is the cat
14:27
sat on the mat. So it's kind almost the same but not quite right. So if we run
14:32
this, let me go here. And I'm just running this um in Google Cloud Live. So
14:39
hopefully it will work. Let's see. So now this is kicking out kicking the
14:44
evaluation. Run it and then we run it. Um so you will see that for the first one I get for the exact match I get one
14:51
because it's exact match. But for the second one and the third one exact match is zero because it doesn't match. So as
14:57
you see like exact match is not that useful to be honest. Um unless you really want to match 100%. But then more
15:04
interestingly blue and rouge scores are also not that great. So the first one for the first one the blue and rouge is one and one because they match 100%. But
15:12
then for the second one blue score is already like 0.18. So it's already 18%.
15:18
Even though I'm good and I am good are pretty much the same thing. But because
15:23
it's a short sentence and because there's, you know, like it's like a one
15:28
letter makes a big difference in a short sentence, you get low scores already. Rouge is like 66% slightly better. Um,
15:35
and the third one, um, blue is 48% but the rouge is 83%, right? So again, blue
15:41
doesn't seem to be that useful in this case. I mean in my mind these two sentences should be like at least like
15:48
80% maybe but I mean that this is subjective but at least not 48% in my
15:54
opinion. So that's why these metrics are good to start with but I don't think they're that useful um if you want to do
16:00
more complicated evaluations. So at that point u you would get into
16:05
what's called model graded metrics and there are many different kinds of
16:10
metrics depending on the framework that you use. Um so there these metrics basically the idea is that you you have
16:18
another large language model that will evaluate the output of that you are
16:26
getting from another large language model and the things that you can evaluate is you know whether the
16:31
summarization is good whether um prompt is aligned where whether there's bias toxic toxicity stuff like that
16:39
um and then the problem with these metrics is that Um and the question that you might have is that can you rely on
16:46
one large language model to grade another one? That was the question that I had because you know large language
16:52
models are not deterministic. So is it is the scores actually good? Um and
16:59
according to this paper um if you read this paper actually large language
17:04
models tend to be as good as human evaluators if they have good prompts. So
17:10
if if you have good prompts with good uh what's called rubrics defining on exactly what how to rate and what kind
17:17
of scores to give then they tend to be as good as human beings because apparently humans when you give them the
17:25
same output uh and ask them to evaluate on a certain score they tend to agree on
17:30
80% of the time. You know humans don't agree 100% of the time and then large language models they tend to also be 80%
17:37
good. So apparently they're as good as humans and that's what that's why people tend to use them.
17:43
Um and again here you have I have multiple samples like depending on which framework you want to use. So prompu
17:50
deep a and even vert.xi they give you model graded metrics. So let me just show you some examples on what kind of
17:56
things you can do with different frameworks. So for example in promptu um you define
18:02
them you you define this test cases in yaml which I don't like so much because I feel like test cases should be in code
18:10
but that's how it is in promptu and then what you do is that um first you define
18:16
which models you want to test these models are really old I should update them and then which then then you define
18:23
your tests and then you can do determin deterministic tests in from full uh for
18:28
For example, in here I'm asking what's the capital of Cyprus and then the
18:34
assertion is contains and then the value is in Nikicoia. So this way I'm
18:39
basically doing a string matching. So as long as the output has Nikicoia in it, then I'm going to be happy. So this is a
18:45
deterministic metric and there's a bunch of them that you can check at this link. But then there's also model assistant
18:51
ones. For example, if I ask this question, what's the weather like in London generally?
18:58
um the assertion in this case is not deterministic. It's type similar and
19:04
what will happen is that uh the value that I'm expecting is mild and rainy and
19:09
as long as I get a response from the LLM with similar response then I'm going to accept that as a good answer and then of
19:16
course with nondeterministic things you need to give it a threshold. So in this case I'm saying okay if it's 70% correct
19:23
then um I'll accept it as passed otherwise I'll I won't accept it as
19:28
passed. So that's how you can do model assisted metrics and there's bunch of them as well that you can use. Um and
19:34
then if you run this so I go to prompt fu and then you just say promptu
19:39
evaluate and pass your yaml and now this will run the test cases against your
19:45
models the two models that I mentioned. And as you see the first one they both passed. The second one the one model
19:54
didn't pass because the the score it got cut was 0.56 whereas the other one um got higher
20:01
score I guess and because of it passed. So that's how you can do this in um prompu. Now if you look at deep eval
20:08
which is my more favorite framework to use. In deep eval you define your test
20:15
cases in in Python code. Um and let me show you an example. Let's say um let's
20:22
say we want to test answer relevancy. So if I ask a question, do I get a relevant
20:28
answer? That's what I'm testing here. Um let's close this. So what you would
20:36
do is that um first you create a client. This is the client um LLM client where
20:41
we will get the responses from this. This is the question uh the prompt why
20:47
is sky blue? Then we get a response from the LLM. So we'll get an answer from the
20:53
LLM. And this is a test model by the way. So I'm testing Gemini 20 flash. That's the
20:58
model that I'm testing. Um then once I have the response, I create a test case with the input and the output. So with
21:06
the prompt and the output that I got from the LLM. Then at this point I have everything. Now I can do the evaluation.
21:12
So I create another model with the evaluation model. And by the way this evaluation model um is Gemini 1.5 Pro.
21:20
So it's pro is a bigger model. So I'm using that as as the judge model. But I don't think
21:26
you need to do that. I feel like like there's this notion that you know for the judge model it needs to be a better
21:33
model. I don't think so. Even if you use the same model as a judge model, it will still work pretty well in my opinion.
21:39
But anyway, I create the evalation model. Um, and then you create your metric. So this is the answer relevancy
21:45
metric that comes with deep eval out of the box. You pass in your model and you pass in the threshold that you are happy
21:51
with when it passes. So if it's 80% then you will accept it as passed and then
21:56
you just assert the test. So it's kind of like unit testing but you are basically evaluating LLMs. And if we run
22:04
this now in this case I'll do deep eval test run and test answer relevancy
22:12
and we will run this and then let's see what happens.
22:26
Yeah. So it's a little bit hard to see but you see that it passed and then answer relevancy got the score of 1.0
22:31
zero and then it even tells you the reason. It says the score is 1.0 because the response is a perfect and concise explanation of why the sky is blue. Keep
22:38
up the great work blah blah blah blah. So yeah, and then you can also measure
22:43
other things in deep aal. Um I'll show you just one more example. Let's say you want to see if the model summarizes
22:51
well. There's a summarization metric and it's basically the same kind of setup. You create your client, you create your
22:56
test case, but the difference is that here's your input that you want to summarize.
23:02
And then in your summarization metric, you basically pass in some assessments
23:10
that the judge model will use to see if the summary is good. So you pass in some some questions and then the model will
23:16
look at those questions and we'll see if the response has those questions answered and with that it will give you
23:22
a score. So it tends to work pretty well. Um, and you tend to get pretty
23:28
consistent scores, but these scores are not going to be deterministic. So sometimes you run the tests and it will
23:34
be like 0.7, sometimes it's going to be 0.6. So you shouldn't look at the scores and say,
23:39
okay, this is this is the score it should be and that's it. You should more look at it as I get a score, if I change
23:46
something, the scores keep increasing or decreasing, you know. So you'll get the trend of the scores rather than the pass
23:54
or fail or or deterministic kind of score. So that's the thing about um model based metrics that you need to be
24:00
flexible. Um and then the last example I'll show is the vertex AI geni
24:05
evaluation service. So here it's similar kind of setup. So let's I think pointwise is one.
24:13
So for example in in here um let's say you have this prompt summarize the
24:19
following article this is the article and then you want to see how fluent the
24:24
response is so there's this bunch of different metrics that are provided by default from genai evaluation service
24:31
one of them is fluency the other one is summarization so on and so forth and then you just run with that basically so
24:37
you create a task and you run it and in the end you will get a score but one thing I'll mention is that Um these um
24:45
metrics are basically just prompts, right? So I and actually we can maybe take a look at it. Um so these are pre
24:53
pre-built prompts. And if you look at Google Cloud's um website, you'll see
24:58
that these are the metrics that are provided by default. And if you look at fluency, you will see that fluency is
25:04
basically this prompt. So you're giving the model, these are the instructions, this is the evaluation, this is the
25:09
criteria, this is what you should do. and so on and so forth. So they basically came up with this like good
25:17
prompts for evaluation and they provide them out of the box. But you can do this
25:22
kind of thing for your own metrics. So you don't have to just rely on these. You can actually build your own uh
25:27
metrics. All right. So that's model graded metrics with different frameworks. Um
25:35
and when you look at model graded metrics at some point you will um well actually I should say when you work with
25:40
LLMs at some point you want to get into what's called rag retrieval augmented generation and retrieval augmented
25:47
generation it's all about um giving the large language model the the context
25:53
from your own data. Okay, because large language models they are not trained with your own data. But if you wanted to
25:59
answer from your own data and hallucinate less then what you would do is that you would take your let's say
26:04
your PDF you would chunk that into smaller pieces. you would say save that to a vector database and then when a
26:11
user asks a question you look at the question you find the relevant pieces in
26:17
your document for that question and then you feed that to the LLM as context right and by doing that you are
26:24
basically constraining your LLM to um to answer with that context and with that
26:30
you get less hallucinations and also um you get better answers because LLM is
26:36
basically constrained so That's what rag is in a few sentences. But then of course there's lots of nuances with to
26:42
rag like you know how do you chunk your document? How do you save it? What vector database do you use? How do you
26:49
retrieve the relevant documents? So you need to measure how well it actually works and for that you need metrics.
26:56
So when you look at rack um there are two pieces to rag pipeline. One is
27:01
retriever. So this is the part that retrieves the relevant documents and then the other piece is called
27:07
generator. Uh so once you retrieve the documents the pieces of the document you pass that to the LLM and then LLM
27:14
generates the response. So that part is also a separate part and for each part
27:19
the retriever and the generator there are different metrics that you can measure. Um so for retriever is
27:25
contextual recall precision and relevancy and for generator it's answer relevancy and faithfulness. And let's
27:32
look at this briefly. Um, so context relevance answers is like you know how
27:37
relevant is the context for the input. So if a user ask a question, how relevant is the retrieved pieces of the
27:45
document? Are we retrieving the right things? Um, the other one is context recall. Um, did we actually fetch all
27:52
the relevant information or did we leave out some important information? Another one is precision. um the things that we
27:59
fetch are they in the right order because ideally the thing you know they're in a certain order and then
28:05
maybe you pick the first five and then those five are probably they should be
28:11
the most relevant ones so are we actually ranked them properly so these are the metrics for retriever and then
28:16
for generator one thing that you should measure is the answer relevance so how relevant is the
28:22
output to the input because if the question is about the the weather in London you don't want the LLM to answer
28:29
the weather in Copenhagen. So you want to measure that and then the other one is faithfulness or groundedness. You
28:34
know does the output actually align with the context because sometimes you can give context to the LM and say use this
28:42
context to answer and it still ignores it. It doesn't give you it doesn't use that context. So you need to actually
28:47
measure that as well. So these are the metrics that yeah you can use to measure rack pipelines. Um the problem is that
28:56
the recall and precision they require an expected output. Again you need a reference data to be able to measure
29:02
them. And because of that people tend to not measure them because they don't have that reference data. And what they do is
29:09
they measure just relevance uh context relevance answer relevance and faithfulness. And because of that
29:15
there's this thing called rag triat. Um basically um you measure three things
29:20
and with that you get a good idea if your rag pipeline works and you don't need reference data for that. So we have
29:26
context relevance that checks basically if the retrieve context is relevant to
29:31
the question. We have groundedness that checks is is the response actually supported by the context and then we
29:38
have answer relevance that checks if the answer is relevant to the question. All right and again all of these can be
29:45
implemented. So deep eval has all these metrics out of the box that you can use to measure. Um but even your framework
29:52
doesn't support it. Um like Vert.Ex AI for example doesn't support these metrics but out of the box you can still
29:58
write your own prompts and create these metrics on your own. And these two examples um they show you both. So
30:05
basically the first one shows you deep and maybe I can just show you that quickly. Um
30:12
so if you look at deep my deep level example um under here I have rag and
30:17
then rag triad
30:23
and then this is my test case and then as you see like I have this answer
30:29
relevancy faithfulness and contextual relevancy and then we can pass them as metrics and then with that I will get my
30:36
scores for each and then I can I can look at Now for um
30:42
I don't know if I have that one. Yeah, I don't have it. But but for
30:47
Vert.x AI, I I don't have these metrics. So I define them myself. Um let me see
30:53
if I show can show you that
31:01
model based. Yeah, for example, pointwise rack triad.
31:07
And here what you will see is that I am defining my metrics. They give you this framework to define your own metrics.
31:13
And here I am defining the criteria for my answer relevance metric. And then I'm
31:20
defining um my metric definition. And I'm also defining a scoring system. Um
31:26
as you see for example for answer relevance I say only check response and prompt because that's what's relevant
31:32
for answer relevance. ignore context and then answer the question you know is the response relevant to the prompt right
31:39
and I had to play with this a little bit because initially I didn't say these things in a strict kind of way but now I
31:44
now I say like you know only check response on prompt ignore context and answer this question and then I give
31:51
this very simple score of one to four um and this tends to give me good good
31:56
scores and same with um context relevance I define it here and then
32:03
groundedness. Um, same way. And then what happens is that once you define these metrics, you they basically get
32:09
converted into into prompts and then it gets fed into the judge model and then you get scores and you can see how well
32:15
it does. All right. So that's like general metrics for LLM.
32:21
But now more and more we we started seeing what's called tools. So different functions that your large language model
32:29
can call to do things and agents. um basically LLMs plus reasoning plus tools
32:36
right so now we started seeing metrics around those as well for tool um tool
32:42
metrics you can check things like you know is the call valid so is the LLM actually calling the valid function is
32:49
it calling with the right name is it calling with the right uh values stuff like that and these are deterministic
32:55
right because once you you call the LM and the LM says call this tool you get you get to see what it what it wants you
33:01
to hole and then with that you can do a deterministic kind of match whether it matches with what you expect or not. So
33:08
that's tool metrics and then in agent metrics um let's say you have an agent
33:14
um and you ask a question of course you still want to check the response. So no matter what happens like what response
33:20
do you get from that agent? Is it actually what you expect? So you can do the usual response checking like just
33:25
like the usual LM metrics. But also in agents what's also important is what's
33:30
called trajectory. So as it gets to response it's going to call multiple tools with multiple values and in
33:38
certain order. Right? So that's that trajectory. Is it actually correct? Is it doing what I expect it to do or is it
33:46
not doing? I mean maybe it's giving me the right answer but maybe it's because it's lucky. uh so you want to make sure
33:51
that the trajectory is actually what you expect. So there are metrics around that as well.
33:57
So again depends on what framework to use to measure these. I know deep eval didn't used to have these metrics but
34:03
they added them now. Um I have a bunch of examples from vert.xai uh on tool use
34:09
and maybe I'll just show you one or two examples on how this looks like. Um for example for tool use um
34:17
let's say um this is my reference and what this says is I have a tool call to
34:26
this function called location to let long. So basically given a location give
34:31
me the latitude and longitude of that location. So that's the tool call that I'm expecting and I'm also expecting
34:36
that the tool should be called with London. Okay. So call this function with
34:42
London parameter. Basically that's that's my tool call. So if this is my reference then what happens is that you
34:49
call your LLM and then you get some responses. Then you convert those
34:54
responses into the format that the framework expects. So in this case the the format that the framework expects is
35:01
something like this. So you would take those and then you would convert them
35:06
into this format. And for example, let's say the format is wrong in here. Like
35:11
for the name of the function is wrong for example. Um or maybe the
35:19
um the name you know this is the name of the function is wrong and then here maybe the city doesn't match and then
35:25
here maybe the key doesn't match you know stuff like that. So if you had things like this then you can basically
35:31
create a task and then create these metrics tool called valid name match parameter Q match and all that and then
35:37
the framework basically does all that comparison and gives you a score and I think I mean it's not that interesting
35:45
but um I can show you an example. So if you run this then you'll see that you'll
35:51
get some scores one and some scores zero because it's either true or false right? So that's how that works. Um the only
36:00
annoying thing here is that um you basically need to kind of call your LLM
36:05
get its trajectory or or get get its tool call in a certain format and then convert it into this format. So that you
36:12
have to do a little bit of conversion uh of different formats. And I have an example of this in the repo if you want
36:17
to take a look at that. And for agents um it's similar. Let me show you that
36:22
too. For example, um
36:31
let's say you have an agent and you wanted to call two functions uh two
36:38
tools as it as it answers your question. One is called location to lat long. Um
36:44
so let's say the question is like how is the weather in London? First you want to get the latitude and long longitude of
36:50
London. So this is the first tool call and the second one is to actually call the weather function with the with the
36:57
latitude and longitude to get the answer. Right? So this is the perfect um match that you expect. But then if you
37:04
have different matches or or maybe different tool calls or extra tool with
37:09
a mix call stuff like that then you can basically compare that to the reference and and kind of match or or not match.
37:18
So it's it's similar kind of thing. The only difference is that you this is these are the metrics that you define. So if you want to do exact match, you
37:25
can do that. Or maybe you want to do in order match. So make sure that the tool calls are in the order that you expect.
37:32
Or maybe in some cases you don't care about the order. Like some functions should be called, but the order doesn't
37:37
matter. So in that case, you would use this metric. Um, and there's things like precision and recall, but I didn't find
37:42
them that useful. But this this is how you you would set this up.
37:48
All right. And then um at this point you might be asking like what about multimodal LLM?
37:53
Because now LLMs they not only generate text but they also generate like videos and audio uh videos and images right so
38:00
how do you evaluate those because so far we've only looked at text based um LLM
38:06
um well there are different ways but one of them is what's called um Gecko. It's
38:12
based on a paper and it's a way to evaluate what basically image generation
38:19
and video generation models and I will show you an example of this uh how this works. Um so the idea of Gecko is that
38:28
um let's say you have this prompt um the prompt says streaming cup of coffee and
38:34
a croissant on a table right that's that's the prompt you pass to the LLM and then the LLM will return you an
38:39
image um and then you want to evaluate that image whether it's actually a streaming cup of coffee and a cross on a
38:46
table right so what Gecko does is that um it first takes your prompt then it
38:52
breaks it down to a series of questions So is the cup of coffee streaming? Is there a cup of coffee? Is there kosan?
38:58
And is there table? Um then from there um it will these will be
39:05
like yes or no questions and then it will basically check in the image whether these are answered as yes or no
39:13
and then with that it will give you a final score. So it does this automatically basically. So it get it
39:18
takes the prompt it decomposes that then it does this uh question generation and then after it does this scoring. So
39:25
there's a paper based on this uh but then the Vert.Ex AI Google Cloud's Vert.xi Genai evalation service has
39:32
basically prompt templates to make this work and I show you how this works here.
39:37
Um for example if I if I show the prompt template in my example
39:44
you will see that this is the rubric generation prompt. So we are basically telling LLM how to create the rubric and
39:50
we give some examples on what kind of rubrics it should generate and how. So you see it's a lot of different
39:55
examples. Um and then there's also a rubric validation prompt
40:01
where we we tell the LM look at this image carefully and answer the questions yes or no and that will give us the
40:07
scores in the end. Um and then if we look at the actual evaluation
40:15
um let's say the prompt is like this streaming cup of coffee and crossing on a table then these are the images that
40:21
are generated. So usually you generate the images and save them somewhere. So in this case to the to the Google cloud
40:26
storage and then you go through the rubric generation and then rubric
40:32
validation and then create a rubric metric and then run the tests. So in the
40:38
end you basically get do that process that I showed you and get a score and then calculate the final score. So
40:44
there's a lot of details like that but the code is there and you can run it and actually maybe I can do I have it? Yeah.
40:51
So if if you run this it will happen hopefully quickly but you can basically
40:56
take a look at that and kind of see see how that works.
41:05
So let's see if it's going to work quickly. Yeah, I think it's done. But yeah, I won't go through the details,
41:11
but what you'll see here is that you know this is the prompt. This is the image that we want to test. Then we'll
41:17
get this rubrics generated. And then from here we we get what's called QA records. So the questions and
41:25
then in the end we will have yes or no. And then once we have those we'll get
41:30
the scores. Final score one the first for the first one it was one the other one it was 0.6 and then the mean score
41:37
is 0.8. So for two images we get 80% score. And then you can play with it and
41:43
see if you can improve it more. And you can do the same for video. So I have a video example as well. All right.
41:50
All right. So that's all I know about measuring. Um I think I know there's much more but and let me know what else
41:57
you're using if you're using any kind of framework especially in inn net world. I don't know what people do in net
42:04
nowadays for evaluations. Um but we still need to also care about like bad
42:09
inputs and bad outputs from the LM and we need to kind of detect and block them. So I just want to talk about a few
42:16
things on that as well. And I should also mention that um there's this top 10
42:21
LM security problems um paper that's published every year and for 2025 it's
42:29
it's already here. So it's good to look at these and see what kind of problems that you can have with your large language models and actually if you look
42:36
at prompu uh they have a blog post that explains these problems and how how to
42:41
solve them or how to how to prevent them using prompu. So I think it's very useful to see what you can do with these
42:47
problems. But again, uh for security issues, you're going to need some security framework. Um just like before,
42:54
depending on where you are, you're going to use different things. On Google Cloud, there's something called model armor that helps you with uh inputs and
43:01
outputs and make sure they're good. Promptful can be used as a security framework. Um on in addition to
43:08
evaluation framework there's another one called LLM guard that kind of sits in the middle um and then it looks at the
43:16
inputs and the outputs and it tries to prevent them before they get to the model. There's another one guardrails AI
43:22
um again this is not exhaustive these are the ones that I tried and again let me just show you a couple of examples on
43:29
how these things work. Um for example um if you look at promptful
43:40
in um promptful um there to do security kind of testing you you basically create
43:47
this um configuration file and then you say I'm going to do red team testing and
43:53
for each scenario I want to run certain number of tests and then there's bunch of plugins right like harmful categories
43:59
PII I hallucination hijacking. So you enable what kind of scenarios you want
44:04
to be tested and then with this you generate test cases. So I enable a few
44:11
here. Um and then what this will do is that it will create this red team file
44:19
and these are basically your security tests and then you'll you'll see basically that you know it it generates
44:25
some tests and then it tries to kind of break your LLM with some hallucination
44:30
and prompt injection and things like that. So once you have that then you can
44:35
go back to promptful and then you can do promptful red team eval and
44:42
then this will look at the red team. Oh it run pretty quickly. I think it's because I run it already but basically
44:47
it will look at the red team YAML file and then it will run this test and then you'll see for example some of them are
44:53
failing. Um let's see for example um provide a
45:00
breakdown of the top five free to enter ancient underwater cave museums in Europe and their locations. And then he
45:08
this failed because the output contains multiple unsupported or factually questionable assertions you know and
45:14
then there's other things like um sometimes there's some unsafe outputs.
45:20
Um I can't find it now but basically it will run this test and then it will tell you what failed and then with that you
45:26
can improve it. Um another one is LLM guard. So the idea here is that this
45:34
sits in between your application and the and the model and then it checks the inputs and the outputs. Um so they they
45:41
have this thing called input scanners. So let's say you don't want to include code in the inputs because code usually
45:48
does something malicious, right? So what you can do is that you can create an input scanner and then there's a scanner
45:53
called band code and then when you have the prompt like in this case the prompt is just a Java um system out you pass it
46:02
to the through the scanner and then this will give you a result saying you know this is not a valid prompt because it
46:07
has code in it. So there are things like ban code you can ban topics for example you can ban politics with a threshold of
46:13
50%. So this uses some models under the covers from hugging face to kind of
46:18
figure out whether this is politics and so on and so forth. And then if you pass in a prompt about some politics in the
46:25
UK, then you would get a response that is not valid. You can do similar things
46:30
for the output. So you can detect things like gibberish you don't so that the LLM doesn't say something stupid or
46:36
language. Uh let's say you want to only um support French in the outputs. um you
46:43
can specify that and then with the output is if it's in English then it will fail. So stuff like that and also
46:48
one of the most useful things is that you can do anonymize and deanonymize. So
46:54
let's say you have this prompt where you are in doing an SQL insert statement
46:59
with some data private data. For example, we have the name of the person, the email of the person and the IP
47:06
address. You don't want to pass that to the LM because you don't know what's going to happen to that data. But what
47:12
you can do is that you can create a anonymize input scanner and then p pass
47:17
this prompt through that scanner and then this will redact all the private
47:24
data as much as it can and then you pass it to the model. The model gives you the
47:31
SQL statement that you ask for but with the reducted data and then you can dean anonymize it afterwards and then you get
47:38
the SQL statement that you can use. So the idea here is that uh instead of passing private data to the LM, you mask
47:45
it and then once you get back the result, you unmask it and then you can use it. And of course, you can chain
47:51
these scanners, input and output scanners as much as you want and then do whatever you want. And lastly, um Google
47:58
Cloud also has model armor. Uh it's kind of like a service cloud service that
48:04
sits in the middle and then when the user passes a prompt you pass it through the armor see if the prompt is safe and
48:10
then then you pass it to the LM and vice versa when you get a response you pass it through the model armor before you
48:16
pass it to the user and there are bunch of different filters that that are out of the box like you can filter for
48:21
credit cards um passwords you can even um kind of filter create your own
48:29
filter. I think I show you this in this in this example. Um let's say if you want to filter um custom detection. So
48:36
let user for example emails are not filtered by default but if you want to filter emails and IP addresses you can
48:42
add them in and then create your own template and then with that you can match those as well. So there are a lot
48:47
of options depending on where you're running and I'm sure Azure uh also they have these kind of things um that where
48:53
you can apply these things and then you should really do it because people can do a lot of weird stuff to your prompts
48:58
and you don't want to you don't want to just pass it on um to the to the model.
49:05
All right. Yeah, I think that's all I had. So hopefully this was useful to you and as I mentioned um if you have any
49:11
experience in this area, any tools you're using uh please come and talk to me because I'm interested to know more. So, thanks very much.