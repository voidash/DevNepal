import {spawn} from 'node:child_process';
import {mkdir, unlink} from 'node:fs/promises';
import path from 'node:path';

const kalaBinary = process.env.KALA_TTS_BIN || 'uvx';
const kalaSpeaker = process.env.KALA_TTS_SPEAKER || 'kala';
const kalaSpeed = process.env.KALA_TTS_LONG_SPEED || '1.10';
const ffmpegBinary = process.env.FFMPEG_BIN || 'ffmpeg';
const usesUvx = !process.env.KALA_TTS_BIN;
const chapterSpeeds = {
  '05-public-profile.mp3': '1.16',
  '06-ministry-create.mp3': '1.10',
  '07-live-refresh.mp3': '1.34',
  '08-github-proof.mp3': '1.18',
  '10-resilience-close.mp3': '1.24',
};

const chapters = [
  [
    '01-public-entry.mp3',
    `यो बीस मिनेटको प्रदर्शन प्रत्यक्ष चलिरहेको डेभनेपालबाट सुरु हुन्छ। पहिलो पटक आउने आगन्तुकले खाता बनाउनु पर्दैन। उसले कुनै GitHub अनुमति दिनु पर्दैन र कुनै लामो व्यक्तिगत विवरण पनि भर्नु पर्दैन। माथिको सार्वजनिक मेनु जानाजानी छोटो छ। सरकारी परियोजना, कसरी योगदान गर्ने, भाषा परिवर्तन र मन्त्रालयका लागि छुट्टै साइन इन मात्र देखिन्छन्। मुख्य सन्देशले डेभनेपालको सीमा स्पष्ट गर्छ। सरकारी प्रविधिको काम यहाँ खोजिन्छ, तर issue, छलफल, commit र pull request GitHub मै रहन्छन्। तलका विशेष सरकारी परियोजना कार्डले आगन्तुकलाई तुरुन्तै वास्तविक काम देखाउँछन्। प्रत्येक कार्डमा जिम्मेवार निकाय, नेपाली र अंग्रेजी शीर्षक, कामको कठिनाइ र अपेक्षित प्रतिक्रिया समय जस्ता निर्णयका लागि चाहिने कुरा छन्। यो सार्वजनिक प्रवेशमा super admin, member dashboard, recognition वा social profile जस्ता असम्बन्धित विकल्प देखाइएका छैनन्। लक्ष्य धेरै feature देखाउनु होइन; आगन्तुकले कुन सरकारी काम खुला छ र अर्को कदम के हो भन्ने केही सेकेन्डमै बुझ्नु हो। अहिले देखिएको पृष्ठ packaged mockup होइन। यो devnepal.zapper.cloud मा चलेको Django application को नेपाली route हो, र भिडियोका सबै public capture यही live deployment बाट लिइएका हुन्।`,
  ],
  [
    '02-project-discovery.mp3',
    `अब सरकारी परियोजनाको catalogue खोलिएको छ। यहाँ चारवटा नमुना परियोजना छन्, तर सूचीको उद्देश्य संख्या ठूलो देखाउनु होइन। आगन्तुकले आधिकारिक ownership, contribution को अवस्था र कामको प्रकृति तुलना गर्न सक्नुपर्छ। filter र status summary ले खुला, रोकिएको वा पूरा भएको काम छुट्याउँछन्। card को hierarchy सरल राखिएको छ, ताकि लामो badge र दोहोरिएको metadata ले मुख्य निर्णय नछोपोस्। हाम्रो end to end उदाहरण नागरिक सहायता निर्देशिका हो। अंग्रेजी repository identifier उस्तै राखिएको छ, जबकि परियोजनाको सार्वजनिक सन्दर्भ नेपालीमा पढ्न सकिन्छ। यो project सूचना प्रविधि विभागसँग जोडिएको छ र नागरिक सहायता कार्यक्रम खोज्न सजिलो बनाउने public repository प्रयोग गर्छ। सूचीबाट detail मा जाने link वास्तविक Django route हो। कुनै account wall छैन। आगन्तुकले ministry sign in नगरी project खोल्न सक्छ। project card ले difficulty, effort, response commitment र सार्वजनिक status देखाउँछ, जसले contributor लाई आफ्नो समय मिल्छ कि मिल्दैन भन्ने निर्णय गर्न मद्दत गर्छ। अन्य परियोजना पनि देखिनुको कारण यो flow एउटै hardcoded card मा सीमित छैन भन्ने देखाउनु हो। तर प्रदर्शनमा हामी एउटै repository लाई गहिरो रूपमा पछ्याउँछौँ, किनकि breadth भन्दा verified flow बढी उपयोगी छ। अब Civic Help Directory खोल्दा project को समस्या, जिम्मेवार निकाय, repository र योगदान सुरु गर्ने ठाउँ एउटै public page मा आउँछन्। यही visitor-first catalogue हाम्रो demo को पहिलो उपयोगी निर्णय बिन्दु हो।`,
  ],
  [
    '03-project-github.mp3',
    `यो नागरिक सहायता निर्देशिकाको live project detail हो। माथिल्लो भागले परियोजनाको उद्देश्य, जिम्मेवार विभाग, contribution को अवस्था र GitHub repository सम्मको बाटो देखाउँछ। तल GitHub बाट synchronized सार्वजनिक snapshot छ। visitor को प्रत्येक page load मा GitHub API बोलाइँदैन। मन्त्रालयले refresh चलाउँदा आएको अन्तिम मान्य snapshot database मा राखिन्छ, र public page ले त्यही timestamp सहित देखाउँछ। यसले GitHub अस्थायी रूपमा ढिलो हुँदा पनि discovery page चलिरहन्छ। अहिले issue सात, आठ, नौ र synchronization जाँचका लागि बनाइएको issue एघार सूचीमा छन्। हाम्रो मुख्य visitor उदाहरण issue सात हो: scholarship program का लागि नेपाली eligibility text थप्ने काम। issue आठ official source विरुद्ध health subsidy contact details जाँच्ने काम हो। issue नौ keyboard-first contribution workflow को documentation हो। issue number र title GitHub का source identifier भएकाले अनुवाद गरेर परिवर्तन गरिएको छैन। Open pull requests भागमा pull request नम्बर दस review मा रहेको देखिन्छ। DevNepal ले open PR लाई पूरा भएको सरकारी उपलब्धि भनेर प्रस्तुत गर्दैन; source मा open भए projection मा open नै देखाउँछ। contributors भागमा repository बाट आएको सार्वजनिक GitHub identity र contribution count देखिन्छ। private email, token, private repository वा hidden organization data आउँदैन। snapshot GitHub App installation बाट server-side मा बन्छ, visitor OAuth बाट होइन। repository bind गर्दा service ले full name र public visibility जाँच गर्छ। refresh पूरा data ल्याउन सफल भएपछि मात्र issues, pull requests, contributors र profile snapshot एउटै transaction मा बदलिन्छन्। बीचमा failure आए आधा नयाँ र आधा पुरानो data मिसिँदैन। project page को मुख्य उपयोग यही हो: brochure मात्र होइन, अहिले कुन खुला काम उपलब्ध छ, code कहाँ छ, review मा के छ र कसले public activity गरेको छ भन्ने एउटै ठाउँमा बुझाउनु। त्यसपछि visitor ले आफ्नो लागि उपयुक्त issue छान्छ।`,
  ],
  [
    '04-issue-handoff.mp3',
    `अब issue नम्बर सात खोलिएको छ। यसको शीर्षक scholarship program का लागि नेपाली eligibility text थप्ने हो। DevNepal भित्र visitor ले Goal, acceptance criteria र कसरी योगदान गर्ने भन्ने पूरा context पढ्न सक्छ। कामले data फाइलमा eligibility ने field थप्न भन्छ। प्रत्येक scholarship मा छोटो नेपाली eligibility हुनुपर्छ, JSON schema मान्य रहनुपर्छ र विद्यमान अंग्रेजी content बदलिनु हुँदैन। केवल “contribute” button राखेर GitHub पठाउँदा नयाँ contributor ले कामको सीमा नबुझ्न सक्छ। त्यसैले handoff अघि आवश्यक issue body सुरक्षित HTML का रूपमा पढाइन्छ। heading, list र inline code स्पष्ट छन्, तर arbitrary script चल्न दिइँदैन। अब तलको Start contributing on GitHub action ले canonical source खोल्छ। GitHub को URL voidash slash civic-help-directory slash issues slash seven हो। त्यहाँ number, title, labels र body यही कामसँग मिल्छन्। assignment, comment, branch, commit र pull request GitHub मै हुन्छन्। DevNepal ले GitHub का collaboration controls नक्कल गर्दैन र visitor को credential लिँदैन। यो सीमा product को कमजोरी होइन; दुई system को जिम्मेवारी स्पष्ट बनाउने निर्णय हो। DevNepal सरकारी context, discovery र ministry accountability दिन्छ। GitHub source code र developer workflow को सत्य स्रोत रहन्छ। issue GitHub मा बदलियो भने publisher को अर्को verified refresh पछि snapshot बदलिन्छ। provider केही समय उपलब्ध नभए पुरानो valid issue र direct GitHub link रहन्छ। यसरी visitor पहिले काम बुझ्छ, त्यसपछि सही source मा पुग्छ, र नयाँ account खोल्नुपर्ने अतिरिक्त friction आउँदैन।`,
  ],
  [
    '05-public-profile.mp3',
    `Project को contributor link खोल्दा public GitHub profile आउँछ। यो पुरानो DevNepal résumé, member account वा अलग social network होइन। नाम, avatar, bio, location, company, public repository र follower जस्ता GitHub ले सार्वजनिक रूपमा दिएका सीमित field मात्र प्रयोग हुन्छन्। तल Activity on connected projects भागमा यो identity कुन DevNepal-connected सार्वजनिक repository मा देखिएको हो भन्ने context छ। यहाँ voidash नागरिक सहायता निर्देशिका repository मा public contributor का रूपमा देखिन्छ। contribution count लाई quality score, सरकारी endorsement वा कर्मचारी ranking बनाइएको छैन। Profile source card ले data GitHub public API बाट आएको र अन्तिम synchronization समय देखाउँछ। मूल github.com profile खोल्ने स्पष्ट link पनि छ। कसैको private email, access token, private contribution वा hidden organization membership render हुँदैन। यस्तो profile हेर्न visitor account आवश्यक छैन। मन्त्रालयले repository activity हेर्दा व्यक्तिको सार्वजनिक source सम्म पुग्न सक्छ, तर DevNepal ले उनीबारे अलग biography बनाउन खोज्दैन। यो screen को मूल्य कम data देखाउनुमै छ: source कहाँ हो, activity कुन project सँग सम्बन्धित छ, snapshot कहिले जाँचिएको हो, र मूल public profile कसरी खोल्ने।`,
  ],
  [
    '06-ministry-create.mp3',
    `अब ministry publisher को flow सुरु हुन्छ। publisher स्थानीय username, password र multi-factor authentication बाट प्रवेश गर्छ। sign in भएपछि member settings वा super-admin console मा होइन, आफ्नो Publishing dashboard मा पुग्छ। त्यहाँ मन्त्रालयका draft र प्रकाशित परियोजना देखिन्छन्। Create project खोल्दा bilingual authoring form आउँछ। presentation मा लामो form manually टाइप गर्न समय नलागोस् भनेर Fill demo details भन्ने सानो helper राखिएको छ। button थिच्दा realistic अंग्रेजी र नेपाली title, summary, problem statement, expected outcome, participation guidance र ministry response commitment भरिन्छन्। helper ले form submit गर्दैन। publisher ले प्रत्येक value review गरेपछि मात्र save गर्छ, त्यसैले demo चलाउँदा अनजाने duplicate project बन्दैन। repository URL मा वास्तविक https github dot com slash voidash slash civic-help-directory राखिन्छ। issue tracker पनि त्यही repository को issues page हो। default branch main, approved licence MIT, contribution mode, difficulty र effort band जस्ता technical contract स्पष्ट छन्। नेपाली summary छुट्टै field मा देखिन्छ र सार्वजनिक page ले चयन गरिएको भाषामा सही content प्रयोग गर्छ। project create गर्नु भनेको code DevNepal मा copy गर्नु होइन। publisher ले सरकारी उद्देश्य, ownership, response commitment र repository binding व्यवस्थापन गर्छ। GitHub App installation ले उपलब्ध public repositories को सूची दिन्छ, र server ले repository full name तथा privacy जाँचेर मात्र connection स्वीकार्छ। personal access token form मा राखिँदैन। अहिलेको footage live deployed authoring page हो। demo-fill पछि repository field मा civic-help-directory आएको assertion Playwright ले जाँचेर मात्र screenshot लिएको छ। यो भागले design मात्र होइन, authentication, Django form, bilingual data र GitHub App boundary एउटै कार्यप्रवाहमा जोडिएको देखाउँछ।`,
  ],
  [
    '07-live-refresh.mp3',
    `अब प्रकाशित project को ministry workspace खुलेको छ। repository card मा voidash slash civic-help-directory, अन्तिम synchronized समय, खुला issues, pull request नम्बर दस र contributor summary देखिन्छ। Refresh GitHub activity button publisher का लागि मात्र हो। यो video मा prerecorded स्थानीय animation होइन। Brave ले devnepal.zapper.cloud मा वास्तविक publisher session, password र verified TOTP प्रयोग गरेर यही deployed button थिचेको हो। request CSRF protected POST हो। server ले repository यही project सँग जोडिएको, public, active र stopped नभएको जाँच गर्छ। signed-in व्यक्ति सक्रिय ministry publisher हुनुपर्छ। अर्को ministry को account ले अनुमान गरेको identifier बाट resource access गर्न सक्दैन। repository अनुसार cooldown reservation लिइन्छ, त्यसैले double click ले provider मा duplicate burst पठाउँदैन। त्यसपछि GitHub App client ले repository metadata, open issues, open pull requests, contributors र आवश्यक public profile data ल्याउँछ। full name र public visibility फेरि verify हुन्छ। response पूरा सफल भएपछि मात्र database transaction भित्र snapshot replace हुन्छ। यस recorded run मा success notice आयो, Last synchronized समय बदलियो, र GitHub को issue एघार workspace मा देखियो। त्यसपछि हामीले public page र source पनि फेरि capture गरेका छौँ। GitHub timeout, invalid credential वा malformed response आए browser मा provider को secret detail आउँदैन। अन्तिम राम्रो snapshot मेटिँदैन, failure audit हुन्छ, र publisher ले फेरि प्रयास गर्न सक्छ। यसलाई continuous realtime stream भन्नु गलत हुन्छ। यो permission-checked, publisher-triggered live refresh हो जसले timestamped public projection बनाउँछ। public visitor को page load छिटो र predictable राख्नुका लागि upstream call यही controlled action मा सीमित छ।`,
  ],
  [
    '08-github-proof.mp3',
    `अब source boundary प्रत्यक्ष GitHub मा जाँचिन्छ। Issues सूचीमा issue नम्बर सात खुला छ: scholarship program का लागि नेपाली eligibility text थप्ने काम। यही number र title DevNepal को issue detail मा देखिएको थियो। GitHub page मा labels, body र conversation को canonical अवस्था छ। Pull requests tab मा नम्बर दस खुला छ र keyboard-only contribution workflow document गर्ने काम review मा छ। DevNepal ले त्यसलाई merged वा completed भनेर गलत रूपमा देखाएको छैन। source मा open छ भने ministry workspace र public snapshot मा open activity का रूपमा आउँछ। visitor ले GitHub मा assignment माग्न, comment गर्न, fork वा branch बनाउन र pull request खोल्न सक्छ। user OAuth हटाइएको सार्वजनिक flow मा पनि synchronization चल्छ, किनकि repository integration server-side GitHub App installation बाट हुन्छ। यस cross-check को उद्देश्य दुई screenshots उस्तै देखाउनु मात्र होइन। पूर्ण boundary प्रमाणित गर्नु हो: GitHub मा वास्तविक सार्वजनिक काम हुन्छ, publisher controlled refresh चलाउँछ, Django validated snapshot राख्छ, visitor ले सरकारी context सहित issue भेट्छ, र योगदान गर्न canonical repository मा फर्कन्छ। DevNepal code host होइन। यो सरकारको project discovery र accountability layer हो।`,
  ],
  [
    '09-mobile-nepali.mp3',
    `अब उही visitor flow तीन सय नब्बे pixel चौडाइको mobile viewport मा देखिन्छ। header compact हुन्छ, भाषा control र menu screen बाहिर जाँदैनन्। नेपाली शीर्षकको line height र spacing स्थिर छन्। home मा मुख्य सन्देश, सरकारी project action र featured cards क्रमसँग stack हुन्छन्। project detail मा title, ministry, status र GitHub actions finger-friendly आकारमा आउँछन्। semantic scroll पछि GitHub का खुला issues heading मात्र होइन, issue सातको पूरा card पनि देखिन्छ। number, title, labels र Read issue action horizontal scroll बिना पढ्न सकिन्छ। Playwright ले document को scroll width viewport भन्दा ठूलो नभएको जाँच गरेपछि मात्र यी frame सुरक्षित गरेको हो। अंग्रेजी र नेपाली बदल्दा route को language prefix र content बदलिन्छ, तर contribution path उही रहन्छ। mobile visitor लाई account, OAuth वा लुकेको desktop navigation खोज्न पर्दैन। browse, project, issue र GitHub handoff सानो screen मा पनि एउटै सीधा क्रमले चल्छ।`,
  ],
  [
    '10-resilience-close.mp3',
    `अन्त्यमा प्रमाणित loop संक्षेप गरौँ। पहिलो, visitor account बिना live DevNepal खोल्छ र जिम्मेवार मन्त्रालयसहित सरकारी project खोज्छ। दोस्रो, project detail मा उद्देश्य, synchronized GitHub issues, open pull request र public contributor activity पढ्छ। तेस्रो, issue नम्बर सातको goal र acceptance criteria DevNepal मा बुझेर canonical GitHub page मा जान्छ। discussion, assignment, commit र pull request GitHub मा हुन्छन्। चौथो, ministry publisher bilingual project form review गर्छ, वास्तविक public repository जोड्छ र आफ्नो workspace बाट GitHub activity refresh गर्छ। पाँचौँ, सफल refresh ले नयाँ timestamp, issues, pull request र contributors को validated public snapshot बनाउँछ। provider failure भए अन्तिम राम्रो snapshot र source link सुरक्षित रहन्छन्। यस narrow demo का लागि super-admin flow, member OAuth र legacy DevNepal profile आवश्यक छैनन्। देखाइएको public navigation पनि त्यही scope अनुसार घटाइएको छ। तर घटाउनु भनेको functionality delete गर्नु होइन; visitor discovery, issue handoff, publisher authoring, MFA, GitHub App refresh र public projection वास्तविक Django code, database र live deployment मा चलिरहेका छन्। आजको भिडियोका screenshots localhost बाट होइन, devnepal.zapper.cloud बाट Brave मार्फत लिइएका हुन्। यही मुख्य सन्देश हो: visitor-first discovery, GitHub-first collaboration, र ministry-verifiable public accountability।`,
  ],
];

const outputDirectory = path.resolve('public/voice-long');
await mkdir(outputDirectory, {recursive: true});

const run = (command, args, label) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {stdio: ['ignore', 'inherit', 'inherit']});
    child.once('error', (error) => reject(new Error(`Unable to start ${label}`, {cause: error})));
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${label} failed: ${signal ? `signal ${signal}` : `exit ${code}`}`));
    });
  });

for (const [filename, text] of chapters) {
  const outputPath = path.join(outputDirectory, filename);
  const rawPath = path.join(outputDirectory, `.${filename}.raw.wav`);
  try {
    await run(
      kalaBinary,
      [
        ...(usesUvx ? ['--from', 'kala-tts', 'kala-tts'] : []),
        text,
        '--speaker',
        kalaSpeaker,
        '--speed',
        chapterSpeeds[filename] || kalaSpeed,
        '--out',
        rawPath,
      ],
      `Kala TTS for ${filename}`,
    );
    await run(
      ffmpegBinary,
      [
        '-y',
        '-loglevel',
        'error',
        '-i',
        rawPath,
        '-af',
        'loudnorm=I=-16:TP=-2:LRA=7',
        '-ar',
        '48000',
        '-ac',
        '1',
        outputPath,
      ],
      `audio normalization for ${filename}`,
    );
  } finally {
    try {
      await unlink(rawPath);
    } catch (error) {
      if (error?.code !== 'ENOENT') {
        throw new Error(`Unable to remove temporary narration for ${filename}`, {cause: error});
      }
    }
  }
}
